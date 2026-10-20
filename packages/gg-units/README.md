# gg-units

Physical quantities that cannot be mixed up: `Length`, `Time`, `Speed`, `Accel`, `Mass`, `Force`, `Angle`, `Pressure`, `Temperature`.
A quantity is made only through a constructor that names its unit (`feet(3.0)`, `knots(250.0)`, `celsius(15.0)`), is stored in SI
units, and adding a `Length` to a `Speed` is a compile error. No run-time cost.

```gg
import "src/units.gg"

fn main():
    d = units.nautical_miles(12.0)
    v = units.knots(120.0)
    print(d.over_speed(v).as_minutes())        # 6
```

Use it as a dependency (`units = { path = "../gg-units" }`, then `import units.units`). Tests: `gg test packages/gg-units/tests`.
Aviation units (knots, feet, feet per minute, nautical miles, hectopascals, inches of mercury) are included. Products and quotients between
kinds are named methods (`speed.times(time)`), because a type has only one `*`.
