# Installed v2412 shrinker-specific parameter audit

This is a source/runtime semantic audit, not another DrivAer mesh attempt.

The generic `layerParameters.C` does not read `layerTerminationAngle` or `detectExtrusionIsland`. Searching only that file would give the wrong conclusion. The installed runtime library contains both parameter strings and the medial-axis termination function. In the installed `medialAxisMeshMover.C`, lines 1385–1389 read the termination angle with default `0.5*featureAngle`; lines 1404–1407 read the island switch with default false. These are supported **medial-axis mover controls**.

The alternate `displacementMotionSolverMeshMover.C` uses the displacement solver and its own thickness/motion logic. The following exposed controls belong to the medial-axis mover, so changing them under `displacementMotionSolver` must not be cited as an active repair: `nSmoothNormals`, `maxThicknessToMedialRatio`, `minMedialAxisAngle`, `layerTerminationAngle`, `detectExtrusionIsland`.

The post-experiment interface update reports these active conditions in physical scales, lists inactive changes in a compound proposal and rejects a proposal that changes only inactive controls. A focused regression test covers inactive-only rejection, compound warnings and switching back to the active shrinker. **This update was not injected into the already-running new DrivAer episode; its code hash and results stay separate.**

| Installed file | SHA256 |
|---|---|
| `src/mesh/snappyHexMesh/lnInclude/layerParameters.C` | `db10a2da27314838600bd4ff06b564b499d2bc8509f5a22a317453f2addecfb2` |
| `src/mesh/snappyHexMesh/lnInclude/medialAxisMeshMover.C` | `49384a3bd73d308f06cd74d1234b63e33d24cb811ba2b9bbc140ee426016d4fb` |
| `src/mesh/snappyHexMesh/lnInclude/displacementMotionSolverMeshMover.C` | `10fbb06a27c51e94335edcc549723e09c20547f545fd6fc899b980c4b31d8e95` |
| `lib/libsnappyHexMesh.so` | `eb635da594acbc96a4d2107fa628cf61b437ea3bc89bed800cd7e6448adcc350` |

This qualifies historical interpretation too: a compound motion-solver trial can improve for other reasons, but improvement cannot be attributed to these medial-only fields. The unchanged old benchmark remains an observation of the actual executed Dicts, including controls that may be inactive under their selected shrinker.
