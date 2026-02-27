use std::env;

#[derive(Clone, Copy)]
struct Params {
    aggression: f64,
    greed: f64,
    safety: f64,
    focus: f64,
}

#[derive(Clone, Copy)]
struct Episode {
    unlock_rate: f64,
    objective_complete: bool,
    stability: f64,
    elapsed_s: f64,
}

struct Lcg {
    state: u64,
}

impl Lcg {
    fn new(seed: u64) -> Self {
        let initial = if seed == 0 { 0x9e3779b97f4a7c15 } else { seed };
        Self { state: initial }
    }

    fn next_u64(&mut self) -> u64 {
        self.state = self
            .state
            .wrapping_mul(6364136223846793005)
            .wrapping_add(1442695040888963407);
        self.state
    }

    fn next_f64(&mut self) -> f64 {
        let x = self.next_u64() >> 11;
        (x as f64) / ((1u64 << 53) as f64)
    }

    fn range(&mut self, lo: f64, hi: f64) -> f64 {
        lo + (hi - lo) * self.next_f64()
    }
}

fn clamp(v: f64, lo: f64, hi: f64) -> f64 {
    if v < lo {
        lo
    } else if v > hi {
        hi
    } else {
        v
    }
}

fn parse_flag(args: &[String], key: &str, default: f64) -> f64 {
    let mut i = 0usize;
    while i + 1 < args.len() {
        if args[i] == key {
            if let Ok(v) = args[i + 1].parse::<f64>() {
                return v;
            }
            return default;
        }
        i += 1;
    }
    default
}

fn parse_flag_u64(args: &[String], key: &str, default: u64) -> u64 {
    let mut i = 0usize;
    while i + 1 < args.len() {
        if args[i] == key {
            if let Ok(v) = args[i + 1].parse::<u64>() {
                return v;
            }
            return default;
        }
        i += 1;
    }
    default
}

fn parse_flag_usize(args: &[String], key: &str, default: usize) -> usize {
    let mut i = 0usize;
    while i + 1 < args.len() {
        if args[i] == key {
            if let Ok(v) = args[i + 1].parse::<usize>() {
                return v.max(1);
            }
            return default;
        }
        i += 1;
    }
    default
}

fn run_episode(params: Params, rng: &mut Lcg) -> Episode {
    let noise = rng.range(-0.08, 0.08);
    let unlock_rate = clamp(
        0.42 * params.aggression
            + 0.36 * params.greed
            + 0.20 * params.focus
            - 0.10 * (params.safety - 0.72).max(0.0)
            + noise,
        0.0,
        1.0,
    );

    let stability = clamp(
        0.62 * params.safety
            + 0.22 * params.focus
            - 0.12 * (params.aggression - params.greed).abs()
            - 0.08 * (params.aggression - 0.82).max(0.0)
            + rng.range(-0.06, 0.06),
        0.0,
        1.0,
    );

    let objective_p = clamp(0.18 + (0.58 * unlock_rate) + (0.24 * stability), 0.01, 0.99);
    let objective_complete = rng.next_f64() < objective_p;

    let mut elapsed_s = 1800.0 * (1.0 - (0.65 * unlock_rate));
    elapsed_s *= 1.0 + rng.range(-0.08, 0.05);
    elapsed_s = clamp(elapsed_s, 80.0, 2000.0);

    Episode {
        unlock_rate,
        objective_complete,
        stability,
        elapsed_s,
    }
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let episodes = parse_flag_usize(&args, "--episodes", 10);
    let seed = parse_flag_u64(&args, "--seed", 1);

    let params = Params {
        aggression: clamp(parse_flag(&args, "--aggression", 0.5), 0.0, 1.0),
        greed: clamp(parse_flag(&args, "--greed", 0.5), 0.0, 1.0),
        safety: clamp(parse_flag(&args, "--safety", 0.5), 0.0, 1.0),
        focus: clamp(parse_flag(&args, "--focus", 0.5), 0.0, 1.0),
    };

    let mut rng = Lcg::new(seed);
    let mut rows: Vec<Episode> = Vec::with_capacity(episodes);
    let mut objective_sum = 0.0f64;
    let mut unlock_sum = 0.0f64;
    let mut stability_sum = 0.0f64;
    let mut elapsed_sum = 0.0f64;

    for _ in 0..episodes {
        let ep = run_episode(params, &mut rng);
        if ep.objective_complete {
            objective_sum += 1.0;
        }
        unlock_sum += ep.unlock_rate;
        stability_sum += ep.stability;
        elapsed_sum += ep.elapsed_s;
        rows.push(ep);
    }

    let n = episodes as f64;
    let objective_rate = objective_sum / n;
    let unlock_rate = unlock_sum / n;
    let stability_rate = stability_sum / n;
    let mean_elapsed_s = elapsed_sum / n;

    print!("{{\"episodes\":[");
    for (idx, ep) in rows.iter().enumerate() {
        if idx > 0 {
            print!(",");
        }
        let oc = if ep.objective_complete { "true" } else { "false" };
        print!(
            "{{\"unlock_rate\":{:.6},\"objective_complete\":{},\"stability\":{:.6},\"elapsed_s\":{:.6}}}",
            ep.unlock_rate, oc, ep.stability, ep.elapsed_s
        );
    }
    print!(
        "],\"aggregate\":{{\"episodes\":{},\"objective_rate\":{:.6},\"unlock_rate\":{:.6},\"stability_rate\":{:.6},\"mean_elapsed_s\":{:.6}}}}}",
        episodes, objective_rate, unlock_rate, stability_rate, mean_elapsed_s
    );
}
