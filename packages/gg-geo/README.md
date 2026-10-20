# gg-geo

Positions on the Earth (WGS84): geodetic (`Lla`) to Earth-centred (`Ecef`) and back, local East-North-Up and North-East-Down frames,
great-circle distance, bearing and destination point (`haversine`, `initial_bearing`, `destination`), and the ellipsoidal inverse problem
(`vincenty_inverse`: reproduces Vincenty's published example to a millimetre).

Angles are radians, lengths metres. `vincenty_inverse` returns `None` for nearly antipodal points. Not included: map projections (UTM,
Lambert), geoid height (EGM96/EGM2008), magnetic declination (WMM), the direct problem on the ellipsoid.
Tests: `gg test packages/gg-geo/tests`.
