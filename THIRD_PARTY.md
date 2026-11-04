# Vendored source references

The existing SDK, support libraries, headers and binaries are preserved. No
moving upstream branch is fetched during a native build.

- ULID specification: [`d0c7170df4517939e70129b4d6462cc162f2d5bf`](https://github.com/ulid/spec/tree/d0c7170df4517939e70129b4d6462cc162f2d5bf).
  Tests pin `01ARZ3NDEKTSV4RRFFQ69G5FAV`, its network bytes and timestamp,
  plus the all-zero and maximum values. The new strict core is implemented here.
- Legacy `suyash/*.hh`: byte-verified against `src/*.hh` at
  [`suyash/ulid@3a46362db2c0f5fece10e59a52bdefbf7eec0877`](https://github.com/suyash/ulid/tree/3a46362db2c0f5fece10e59a52bdefbf7eec0877).
  This verifies correspondence, not the historical import date. License:
  [suyash/LICENSE](suyash/LICENSE).
- `4D Plugin API`: retained from this repository's immutable baseline
  [`2620b08`](https://github.com/miyako/4d-plugin-ULID/tree/2620b08/4D%20Plugin%20API).
  Its original upstream revision was not recorded; no claim of an independently
  verified SDK upstream commit is made. Copyright notices in the files reference
  the MIT license, preserved in [4D Plugin API/LICENSE](4D%20Plugin%20API/LICENSE).
  The license was retrieved from the tutorial's pinned SDK revision
  `cd97d1876d4258b56d2516e8ad2816f4ee93e0b5` (`LICENSE.md`).
- Tutorial guidance inspected at
  [`miyako/4d-plugin-tutorial@f8e20f052407c3e74c33192884dc82b31a2bd27a`](https://github.com/miyako/4d-plugin-tutorial/tree/f8e20f052407c3e74c33192884dc82b31a2bd27a).
  Its manifest type table is not an ABI authority: real-host tests established
  classic BLOB `O` and native double `8`. The tutorial repository was not modified.

The existing `include/json`, `support`, `lib` and test fixture dylib are not
linked by the new CMake build. Their existing files are not replaced.
