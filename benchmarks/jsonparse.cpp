// JSON: write 200,000 user records as one JSON text, parse it into a tree of values (a
// recursive variant with vectors of members), and walk the tree. Number and string parsing,
// many small heap allocations, and recursion. The parser is the same in all three languages.
#include <cstdint>
#include <cstdio>
#include <memory>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

struct Member;

struct Json {
    enum Kind { Null, Bool, Num, Str, Arr, Obj } kind = Null;
    bool b = false;
    double num = 0;
    std::string str;
    std::vector<Json> arr;
    std::vector<Member> obj;
};

struct Member {
    std::string key;
    Json val;
};

struct Parser {
    std::string_view text;
    size_t pos = 0;

    void ws() {
        while (pos < text.size() && (text[pos] == ' ' || text[pos] == '\n')) pos++;
    }

    std::string string() {
        pos++;  // the opening quote
        std::string out;
        while (text[pos] != '"') {
            char c = text[pos];
            if (c == '\\') {
                pos++;
                char e = text[pos];
                out.push_back(e == 'n' ? '\n' : e);
            } else {
                out.push_back(c);
            }
            pos++;
        }
        pos++;
        return out;
    }

    double number() {
        bool neg = text[pos] == '-';
        if (neg) pos++;
        double v = 0.0;
        while (pos < text.size() && text[pos] >= '0' && text[pos] <= '9') {
            v = v * 10.0 + double(text[pos] - '0');
            pos++;
        }
        if (pos < text.size() && text[pos] == '.') {
            pos++;
            double scale = 0.1;
            while (pos < text.size() && text[pos] >= '0' && text[pos] <= '9') {
                v += double(text[pos] - '0') * scale;
                scale *= 0.1;
                pos++;
            }
        }
        return neg ? -v : v;
    }

    Json value() {
        ws();
        char c = text[pos];
        Json j;
        if (c == '{') {
            pos++;
            j.kind = Json::Obj;
            ws();
            if (text[pos] == '}') {
                pos++;
                return j;
            }
            while (true) {
                ws();
                std::string key = string();
                ws();
                pos++;  // ':'
                Json v = value();
                j.obj.push_back(Member{std::move(key), std::move(v)});
                ws();
                char c2 = text[pos++];
                if (c2 == '}') return j;
            }
        }
        if (c == '[') {
            pos++;
            j.kind = Json::Arr;
            ws();
            if (text[pos] == ']') {
                pos++;
                return j;
            }
            while (true) {
                j.arr.push_back(value());
                ws();
                char c2 = text[pos++];
                if (c2 == ']') return j;
            }
        }
        if (c == '"') {
            j.kind = Json::Str;
            j.str = string();
            return j;
        }
        if (c == 't') { pos += 4; j.kind = Json::Bool; j.b = true; return j; }
        if (c == 'f') { pos += 5; j.kind = Json::Bool; return j; }
        if (c == 'n') { pos += 4; return j; }
        j.kind = Json::Num;
        j.num = number();
        return j;
    }
};

struct Totals {
    double nums = 0;
    int64_t chars = 0, trues = 0, nodes = 0;
};

static void walk(const Json& j, Totals& t) {
    t.nodes++;
    switch (j.kind) {
        case Json::Null: break;
        case Json::Bool: if (j.b) t.trues++; break;
        case Json::Num: t.nums += j.num; break;
        case Json::Str: t.chars += (int64_t)j.str.size(); break;
        case Json::Arr: for (const Json& x : j.arr) walk(x, t); break;
        case Json::Obj:
            for (const Member& m : j.obj) {
                t.chars += (int64_t)m.key.size();
                walk(m.val, t);
            }
            break;
    }
}

int main() {
    std::string text = "[";
    char buf[256];
    for (int i = 0; i < 200000; i++) {
        if (i > 0) text += ",\n";
        snprintf(buf, sizeof buf, "{\"id\": %d, \"name\": \"user %d\", \"score\": %d.25, \"active\": %s, ", i, i,
                 i % 1000, i % 3 == 0 ? "true" : "false");
        text += buf;
        snprintf(buf, sizeof buf, "\"tags\": [\"t%d\", \"q\\\"%d\"], \"parent\": null, \"pos\": {\"x\": -%d.5, \"y\": %d}}",
                 i % 7, i % 11, i % 50, i % 9);
        text += buf;
    }
    text += "]";
    Parser p{text, 0};
    Json doc = p.value();
    Totals t;
    walk(doc, t);
    printf("%zu %lld %lld %lld %lld\n", text.size(), (long long)t.nodes, (long long)t.chars, (long long)t.trues,
           (long long)t.nums);
}
