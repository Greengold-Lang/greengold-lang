// JSON: write 200,000 user records as one JSON text, parse it into a tree of values (a
// recursive enum with vectors of members), and walk the tree. Number and string parsing,
// many small heap allocations, and recursion. The parser is the same in all three languages.
use std::fmt::Write;

enum Json {
    Null,
    Bool(bool),
    Num(f64),
    Str(String),
    Arr(Vec<Json>),
    Obj(Vec<Member>),
}

struct Member {
    key: String,
    val: Json,
}

struct Parser<'a> {
    text: &'a [u8],
    pos: usize,
}

impl<'a> Parser<'a> {
    fn ws(&mut self) {
        while self.pos < self.text.len() && (self.text[self.pos] == b' ' || self.text[self.pos] == b'\n') {
            self.pos += 1;
        }
    }

    fn string(&mut self) -> String {
        self.pos += 1; // the opening quote
        let mut out: Vec<u8> = Vec::new();
        while self.text[self.pos] != b'"' {
            let c = self.text[self.pos];
            if c == b'\\' {
                self.pos += 1;
                let e = self.text[self.pos];
                out.push(if e == b'n' { b'\n' } else { e });
            } else {
                out.push(c);
            }
            self.pos += 1;
        }
        self.pos += 1;
        String::from_utf8(out).unwrap()
    }

    fn number(&mut self) -> f64 {
        let neg = self.text[self.pos] == b'-';
        if neg {
            self.pos += 1;
        }
        let mut v = 0.0;
        while self.pos < self.text.len() && self.text[self.pos].is_ascii_digit() {
            v = v * 10.0 + (self.text[self.pos] - b'0') as f64;
            self.pos += 1;
        }
        if self.pos < self.text.len() && self.text[self.pos] == b'.' {
            self.pos += 1;
            let mut scale = 0.1;
            while self.pos < self.text.len() && self.text[self.pos].is_ascii_digit() {
                v += (self.text[self.pos] - b'0') as f64 * scale;
                scale *= 0.1;
                self.pos += 1;
            }
        }
        if neg { -v } else { v }
    }

    fn value(&mut self) -> Json {
        self.ws();
        let c = self.text[self.pos];
        if c == b'{' {
            self.pos += 1;
            let mut members = Vec::new();
            self.ws();
            if self.text[self.pos] == b'}' {
                self.pos += 1;
                return Json::Obj(members);
            }
            loop {
                self.ws();
                let key = self.string();
                self.ws();
                self.pos += 1; // ':'
                let val = self.value();
                members.push(Member { key, val });
                self.ws();
                let c2 = self.text[self.pos];
                self.pos += 1;
                if c2 == b'}' {
                    return Json::Obj(members);
                }
            }
        }
        if c == b'[' {
            self.pos += 1;
            let mut items = Vec::new();
            self.ws();
            if self.text[self.pos] == b']' {
                self.pos += 1;
                return Json::Arr(items);
            }
            loop {
                items.push(self.value());
                self.ws();
                let c2 = self.text[self.pos];
                self.pos += 1;
                if c2 == b']' {
                    return Json::Arr(items);
                }
            }
        }
        match c {
            b'"' => Json::Str(self.string()),
            b't' => { self.pos += 4; Json::Bool(true) }
            b'f' => { self.pos += 5; Json::Bool(false) }
            b'n' => { self.pos += 4; Json::Null }
            _ => Json::Num(self.number()),
        }
    }
}

struct Totals {
    nums: f64,
    chars: i64,
    trues: i64,
    nodes: i64,
}

fn walk(j: &Json, t: &mut Totals) {
    t.nodes += 1;
    match j {
        Json::Null => {}
        Json::Bool(b) => {
            if *b {
                t.trues += 1;
            }
        }
        Json::Num(x) => t.nums += x,
        Json::Str(s) => t.chars += s.len() as i64,
        Json::Arr(items) => {
            for x in items {
                walk(x, t);
            }
        }
        Json::Obj(members) => {
            for m in members {
                t.chars += m.key.len() as i64;
                walk(&m.val, t);
            }
        }
    }
}

fn main() {
    let mut text = String::from("[");
    for i in 0..200000 {
        if i > 0 {
            text.push_str(",\n");
        }
        write!(text, "{{\"id\": {}, \"name\": \"user {}\", \"score\": {}.25, \"active\": {}, ", i, i, i % 1000, i % 3 == 0).unwrap();
        write!(text, "\"tags\": [\"t{}\", \"q\\\"{}\"], \"parent\": null, \"pos\": {{\"x\": -{}.5, \"y\": {}}}}}", i % 7, i % 11, i % 50, i % 9).unwrap();
    }
    text.push(']');
    let mut p = Parser { text: text.as_bytes(), pos: 0 };
    let doc = p.value();
    let mut t = Totals { nums: 0.0, chars: 0, trues: 0, nodes: 0 };
    walk(&doc, &mut t);
    println!("{} {} {} {} {}", text.len(), t.nodes, t.chars, t.trues, t.nums as i64);
}
