// GPL-3.0-only. CGAL 5.6.2 independent exact-predicate surface audit.
#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Surface_mesh.h>
#include <CGAL/IO/polygon_soup_io.h>
#include <CGAL/Polygon_mesh_processing/polygon_soup_to_polygon_mesh.h>
#include <CGAL/Polygon_mesh_processing/self_intersections.h>
#include <CGAL/Polygon_mesh_processing/connected_components.h>
#include <CGAL/Polygon_mesh_processing/orientation.h>
#include <CGAL/Polygon_mesh_processing/measure.h>
#include <CGAL/boost/graph/helpers.h>
#include <fstream>
#include <iostream>
#include <iomanip>
#include <vector>
#include <chrono>
using K=CGAL::Exact_predicates_inexact_constructions_kernel;
using Mesh=CGAL::Surface_mesh<K::Point_3>;
namespace PMP=CGAL::Polygon_mesh_processing;

int main(int argc,char** argv) {
  try {
    if(argc!=3||std::ifstream(argv[2]).good()) return 2;
    auto start=std::chrono::steady_clock::now();
    std::vector<K::Point_3> points;std::vector<std::vector<std::size_t>> polygons;
    if(!CGAL::IO::read_polygon_soup(argv[1],points,polygons)||polygons.empty()) return 2;
    if(!PMP::is_polygon_soup_a_polygon_mesh(polygons)) return 3;
    Mesh mesh;PMP::polygon_soup_to_polygon_mesh(points,polygons,mesh);
    const bool valid=CGAL::is_valid_polygon_mesh(mesh),closed=CGAL::is_closed(mesh);
    if(!CGAL::is_triangle_mesh(mesh)) return 3;
    std::size_t degenerate=0;
    for(auto f:mesh.faces()) {
      auto h=halfedge(f,mesh);
      if(CGAL::collinear(mesh.point(source(h,mesh)),mesh.point(target(h,mesh)),mesh.point(target(next(h,mesh),mesh)))) ++degenerate;
    }
    auto component_map=mesh.add_property_map<Mesh::Face_index,std::size_t>("f:component",0).first;
    const auto components=PMP::connected_components(mesh,component_map);
    const bool intersects=PMP::does_self_intersect(mesh);
    const bool outward=closed&&!intersects&&PMP::is_outward_oriented(mesh);
    const double volume=closed?PMP::volume(mesh):0.;
    const bool accepted=valid&&closed&&!intersects&&outward&&volume>0&&components==1&&degenerate==0;
    const double seconds=std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
    std::ofstream receipt(argv[2]);receipt<<std::setprecision(17)<<std::boolalpha
      <<"{\"validator\":\"CGAL 5.6.2 EPICK\",\"valid_polygon_mesh\":"<<valid
      <<",\"closed\":"<<closed<<",\"self_intersecting\":"<<intersects
      <<",\"outward\":"<<outward<<",\"volume\":"<<volume
      <<",\"components\":"<<components<<",\"degenerate_triangles\":"<<degenerate
      <<",\"faces\":"<<mesh.number_of_faces()<<",\"accepted\":"<<accepted<<",\"seconds\":"<<seconds<<"}\n";
    std::cout<<"faces "<<mesh.number_of_faces()<<"; self-intersects "<<intersects<<"; accepted "<<accepted<<"\n";
    return accepted?0:4;
  } catch(const std::exception& e) {std::cerr<<e.what()<<"\n";return 5;}
}
