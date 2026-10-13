// GPL-3.0-only. Separate derived-geometry experiment; never overwrite the source.
// CGAL 5.6.2 Alpha_wrap_3 and bounded-error symmetric Hausdorff validation.
#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Surface_mesh.h>
#include <CGAL/alpha_wrap_3.h>
#include <CGAL/IO/polygon_soup_io.h>
#include <CGAL/boost/graph/IO/polygon_mesh_io.h>
#include <CGAL/Polygon_mesh_processing/polygon_soup_to_polygon_mesh.h>
#include <CGAL/Polygon_mesh_processing/self_intersections.h>
#include <CGAL/Polygon_mesh_processing/distance.h>
#include <CGAL/boost/graph/helpers.h>
#include <array>
#include <chrono>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <vector>

using K=CGAL::Exact_predicates_inexact_constructions_kernel;
using Mesh=CGAL::Surface_mesh<K::Point_3>;
namespace PMP=CGAL::Polygon_mesh_processing;

int main(int argc,char** argv) {
  try {
    if(argc!=7) { std::cerr << "source output alpha_m offset_m tolerance_m distance_error_m\n"; return 2; }
    const double alpha=std::stod(argv[3]),offset=std::stod(argv[4]);
    const double tolerance=std::stod(argv[5]),error=std::stod(argv[6]);
    if(!(std::isfinite(alpha)&&std::isfinite(offset)&&std::isfinite(tolerance)&&std::isfinite(error)
         &&alpha>0&&offset>0&&error>0&&error<tolerance)) return 2;
    if(std::ifstream(argv[2]).good()) { std::cerr << "output already exists\n"; return 2; }
    auto start=std::chrono::steady_clock::now();
    std::vector<K::Point_3> points;
    std::vector<std::vector<std::size_t>> polygons;
    if(!CGAL::IO::read_polygon_soup(argv[1],points,polygons)||polygons.empty()) return 2;
    std::vector<std::array<std::size_t,3>> triangles;
    for(const auto& p:polygons) {
      if(p.size()!=3) { std::cerr << "input must be a triangle soup\n"; return 2; }
      triangles.push_back({p[0],p[1],p[2]});
    }
    Mesh original;
    if(!PMP::is_polygon_soup_a_polygon_mesh(polygons)) {
      std::cerr << "source connectivity cannot be used for distance certificate\n"; return 2;
    }
    PMP::polygon_soup_to_polygon_mesh(points,polygons,original);
    const bool source_intersects=PMP::does_self_intersect(original);
    std::cerr << "input faces " << polygons.size() << "; source self-intersects " << source_intersects << "\n";
    Mesh wrapped;
    CGAL::alpha_wrap_3(points,triangles,alpha,offset,wrapped);
    const bool closed=CGAL::is_closed(wrapped),intersection=PMP::does_self_intersect(wrapped);
    if(!closed||intersection||wrapped.number_of_faces()==0) return 3;
    if(!CGAL::IO::write_polygon_mesh(argv[2],wrapped,CGAL::parameters::stream_precision(17).use_binary_mode(false))) return 3;
    // The original can self-intersect; distance comparison only needs triangle geometry.
    const double distance=PMP::bounded_error_symmetric_Hausdorff_distance<CGAL::Sequential_tag>(original,wrapped,error);
    const double upper=distance+error;
    const bool accepted=std::isfinite(distance)&&upper<=tolerance;
    const double seconds=std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
    std::ofstream receipt(std::string(argv[2])+".metrics.json");
    receipt << std::boolalpha << std::setprecision(17)
      << "{\"cgal_version\":\"5.6.2\",\"source_self_intersecting\":" << source_intersects
      << ",\"source_faces\":" << polygons.size() << ",\"derived_faces\":" << wrapped.number_of_faces()
      << ",\"alpha_metres\":" << alpha << ",\"offset_metres\":" << offset
      << ",\"hausdorff_estimate_metres\":" << distance << ",\"distance_error_bound_metres\":" << error
      << ",\"certified_distance_upper_metres\":" << upper << ",\"tolerance_metres\":" << tolerance
      << ",\"closed\":" << closed << ",\"derived_self_intersecting\":" << intersection
      << ",\"geometry_distance_accepted\":" << accepted << ",\"seconds\":" << seconds << "}\n";
    std::cout << "wrap faces " << wrapped.number_of_faces() << "; Hausdorff upper " << upper << "; accepted " << accepted << "\n";
    return accepted?0:4;
  } catch(const std::exception& e) { std::cerr << e.what() << "\n"; return 5; }
}
