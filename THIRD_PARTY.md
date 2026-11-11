# Third-party components

This project contains no third-party source code and ships no binaries or audio
assets. It calls two libraries at runtime.

| Component | Purpose | License | Upstream |
|---|---|---|---|
| NumPy | array math and the seeded generator | BSD-3-Clause (the reference distribution also bundles 0BSD, MIT, Zlib and CC0-1.0 components; binary wheels add their own notices) | https://numpy.org |
| SciPy | `lfilter` for synthesis noise filtering and `resample_poly` for inter-sample peak estimation | BSD-3-Clause (binary wheels bundle additional permissively licensed components) | https://scipy.org |

Development only:

| Component | Purpose | License |
|---|---|---|
| pytest | test runner | MIT |

No authorship of these components is claimed. The synthesis, the preset schema,
the measurement code and the delivery gate are original to this project.

The gate reports an *estimated* inter-sample peak from 4x oversampling; it is
not certified BS.1770 true-peak measurement.
