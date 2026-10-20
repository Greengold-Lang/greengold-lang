# Greengold: çok alanlı kullanım için eksik analizi ve yol haritası

Kapsam: havacılık, gömülü, savunma, finans, sistem/sunucu. Bu belge `docs/API.md`, `docs/SPEC.md`,
`greengold/std/*.gg`, `greengold/targets.py` ve `cli.py` üzerinden çıkarıldı. Okunmayan/doğrulanmayan yerler
"doğrulanmadı" diye işaretlidir.

## 0. Özet

Dil çekirdeği güçlü: bellek güvenliği, taşma/sınır kontrolü `--release` içinde de açık, `--no-std`,
`cortex-m4`/`wasm32`/RISC-V hedefleri, `allocator` satırı, `volatile_read/write`, `asm`, `packed`/`align`,
atomikler, SIMD, DWARF, `gg test`. Ama **std kütüphanesi "genel amaçlı" olmaktan uzak**: 9.1k satırın
yaklaşık 3.9k'sı (tensor, nn, llama, kquant, gguf, tokenizer, sampler, mmap) LLM çıkarımı; temel
modüllerin (math, fs, io, process, thread, time) kapsamı dar. Sertifikasyon, deterministiklik ve
`no_std` kütüphane hikâyesi neredeyse yok.

## 1. Kütüphane adı–içerik denetimi

| Modül | Adın hakkını veriyor mu? | Bulgu |
|---|---|---|
| `std.math` | Hayır | Sadece f64 ve libm'in küçük bir alt kümesi: `asin/acos/atan/sinh/cosh/tanh/log2/log10/round/trunc/hypot/cbrt/copysign/is_nan/is_inf` yok. f32 sürümleri yok. Generic `min/max/clamp/abs` yok (`min_i64`, `abs_f64` gibi son ekli adlar). Tamsayı matematiği (`isqrt`, `lcm`, checked/saturating `pow`, `popcount`, `rotate`, `bswap`, `leading_zeros`) yok. `e_const` adı tutarsız. |
| `std.string` | Kısmen | `str` metotlarını core'daki ile kopyalıyor (`str_starts_with` vs `s.starts_with`): iki API. Her şey bayt/ASCII; Unicode (normalizasyon, büyük/küçük harf, grapheme) yok, `to_upper` ASCII. |
| `std.fs` | Hayır | `read_file_to_string` hata nedeni vermeden `Optional`; `write_*` `bool`. İkili okuma/yazma, boyut/mtime/izin, `remove_dir`, özyinelemeli gezme, `copy`, `canonicalize`, geçici dosya, atomik yazma (temp+rename+fsync) yok. `list_dir` bir `Optional[string]` döndürüyor, liste değil (ad yanıltıcı). `fgetc/fputc` ile bayt bayt okuma performans riski (doğrulanmadı). |
| `std.io` | Hayır | Sadece `File`. stdin/stdout/stderr akışı, `Reader`/`Writer` feature'ları, tamponlu okuma, `Cursor` yok. |
| `std.process` | Zayıf | `process_run` `system()` + geçici dosya üzerine kurulu: boru (pipe), stdin, ortam/cwd ayarı, asenkron `spawn`, sinyal yok. Kabuk enjeksiyonu riski için argüman kaçışı var ama tasarım kırılgan. |
| `std.collections` | İyi, eksikli | `HashMap/Set/Deque/Heap/SortedMap/Arena` var. Yok: `SortedSet`, `BitSet`, halka tampon, **sabit kapasiteli (heapless) kapsayıcılar**, `SmallVec`, bağlı liste. Hash tohumlaması/DoS direnci belgelenmemiş (doğrulanmadı). |
| `std.sort` | Kısmen | Heapsort (`sift_down`): kararsız, önbellek dostu değil. Kararlı sıralama, `sort_unstable`, `select_nth`, `is_sorted` yok. |
| `std.rand` | Yeterli, dar | xorshift64* ve OS entropisi. Dağılımlar (normal, üstel), karıştırma (`shuffle`), CSPRNG (ChaCha) yok. |
| `std.thread` | Abartılı ad | `Channel` yalnızca `i64` taşıyor (genel olan `Queue[T]`); `AtomicI64` ve `Atomic[i64]` yinelenen, adlandırma tutarsız (`compare_and_swap` vs `compare_exchange`). `RwLock`, `Semaphore`, `Barrier`, `Once`, thread-local, `try_lock`, zaman aşımlı `Cond.wait`, öncelik/afinite yok. |
| `std.parallel` | Dar | Sadece `for_range`. `map/reduce/scope/join` yok. |
| `std.tasks` | Deneysel | POSIX `ucontext` gerçekleştirmesi az test edilmiş (README'de belirtilmiş). |
| `std.time` | Hayır (finans/havacılık için) | Sadece UTC. Saat dilimi/DST, `Duration` türü, biçim/ayrıştırma ailesi (yalnızca ISO), takvim aritmetiği (ay/yıl ekleme), iş günü, GPS/TAI/UTC dönüşümü, artık saniye yok. |
| `std.json` | Finans için riskli | Sayı yalnızca `f64`: 2^53 üzeri `i64` ve parasal değer sessizce bozulur. |
| `std.net` / `std.http` | Kısmen | **Yalnızca IPv4**, epoll/kqueue/IOCP yok, multicast yok; seri port (UART), CAN, USB yok. `std.http` istemci/sunucu var, HTTP/2, WebSocket yok. |
| `std.tls` | Dar | Yalnızca istemci. Sunucu, mTLS, sertifika sabitleme (pinning), TLS sürüm/şifre politikası yok. FIPS yok. |
| `std.packet` | İyi başlangıç | `put_i16/i32/i64/f32/f64` yalnızca little-endian (BE sadece işaretsiz): ARINC 429, MIL-STD-1553, CCSDS, Modbus, FIX gibi big-endian protokoller için eksik. Bit alanı, CRC/checksum yok. |
| `std.sock` | Dahili ayrıntı | Public ama TLS/net'in iç boruları; `private` olmalı ya da `std.net.raw` altına. |
| `std.intern`, `std.mmap` | Uygun | `mmap` yalnızca okuma; yazılabilir/paylaşılan eşleme yok. |
| `std.tensor/nn/llama/gguf/kquant/tokenizer/sampler` | Std'ye ait değil | Alan-özel (≈%43 std). Ayrı pakete (`gg-ml`) taşınmalı; std dar ve denetlenebilir kalsın. |

**Hiç olmayan temel modüller:** kriptografi (SHA-2/3, HMAC, AES-GCM, ChaCha20-Poly1305, Ed25519, sabit zamanlı
karşılaştırma, CRC32/CRC16/Adler), `base64`/`hex`, sıkıştırma (zlib/deflate), CSV/TOML/XML, UUID,
`bits` (popcount, rotate, bswap), `endian`, `log`, komut satırı ayrıştırıcı, `assert_eq`/özellik testi,
`BigInt`, `Decimal`, sabit nokta (fixed-point), karmaşık sayı, doğrusal cebir (küçük matris, kuaterniyon),
istatistik, FFT, kontrol (PID/Kalman).

## 2. Dil/araç zinciri eksikleri (alan bazında)

### Gömülü / havacılık / savunma ortak
1. **Gerçek `no_std` kütüphanesi yok.** `--no-std` "`print` ve heap yok" demek; ama `std.*` modüllerinden hangisinin
   `no_std`'de çalıştığı belirtilmiyor. Kapsayıcı, `math`, `packet`, `sort`, `string` heap'siz/`allocator`'lı kullanılabilmeli ve
   `gg` bunu derleme zamanında doğrulamalı (`#![no_std]` benzeri `gg.toml` bayrağı + hata).
2. **Kesme/başlangıç/bağlama:** `@interrupt`, `@section(".name")`, `@naked`, `@used`, `@weak`, `@export_c`, `@inline(always|never)`
   yok. Attribute'lar yalnızca kullanıcı tanımlı meta veri (`attrs.py`: "derleyici anlam yüklemez"). Vektör tablosu, `_start`,
   `.bss/.data` ilklendirme ve **linker script** desteği yok; `cortex-m4` hedefi sadece triple takma adı.
3. **Bellek-eşlemeli G/Ç:** yalnızca ham `volatile_read/write`. Tipli kayıt (register) tanımı (`mmio struct`, bit alanları,
   `svd2gg` üreteci) yok. `packed` var ama bit-field yok.
4. **Panik politikası sabit:** `--no-std`'de panik = trap. Özel `panic_handler`, "panic=abort/log/reset" seçeneği, ve hata durumunda
   güvenli duruma geçiş yok. Genel olarak **panic'siz alt küme** (`Result` ile tüm yollar; indeksleme/taşma kontrolünün hata kodu
   döndüren varyantı: `checked_index`, `get(i)`) şart.
5. **Deterministik ve sınırlı kaynak analizi:** yığın kullanımı analizi (`gg stack-usage`), özyineleme yasağı denetimi
   (`--forbid-recursion`), dinamik bellek yasağı (`--forbid-heap`), döngü sınırı / WCET desteği yok.
6. **Türler:** `i128/u128` ve `f16` yok (para, zaman damgası ns, hash, ML için gerekli). `bf16` yok. Sabit nokta türü (Q-format) yok.
   `f32` matematik işlevleri yok (FPU'su tek duyarlı MCU'lar için).
7. **Kayan nokta determinizmi:** hızlı-matematik/FMA daralması ve platformlar arası bit-bit aynı sonuç garantisi belgelenmemiş;
   `--cpu native` bunu bozabilir. Uçuş/finans için "strict IEEE" modu ve doğrulama gerekir.
8. **Çoklu çekirdek/RTOS:** FreeRTOS/Zephyr/RTEMS/ARINC 653 bağlama katmanı yok; `std.thread` yalnızca POSIX/Windows.
9. **Hata ayıklama/kalite:** MISRA/CERT-benzeri bir "güvenli profil" (`gg check --profile safety`) ve kapsama aracı (satır/dal/MC/DC)
   yok; fuzz araçları (`tools/fuzz_*.py`) var ama derleyici güvenliği için, kullanıcı programı için `gg fuzz` yok.

### Sertifikasyon (DO-178C/DO-330, ISO 26262, IEC 61508, Common Criteria)
- Derleyici **Python + llvmlite** olarak yazılmış; araç nitelendirmesi (tool qualification) neredeyse imkânsız ve self-host
  dondurulmuş (`SELFHOST_PLAN.md`). Orta vadede: (a) derleyici çıktısının bağımsız doğrulanması (LLVM IR → nesne → statik analiz),
  (b) tekrarlanabilir derleme (aynı girdi → aynı bayt) testi, (c) gereksinim↔test izlenebilirlik matrisi (`conformance/` iyi bir
  zemin), (d) SBOM ve imzalı sürümler.
- Dil hâlâ 0.x, "Do not use it for anything that must be correct yet" (README). Kararlılık sözü (1.0 + edition) şart.
- Tasarım-sözleşmesi (`requires/ensures/invariant`) ve statik kanıt (SMT) yok; gelecekte alt küme için düşünülebilir.

### Finans
- `Decimal` (sabit ondalık, banker's rounding ve mod seçimi), `i128`, `Money`/para birimi türü, taşma-güvenli ölçekli aritmetik yok.
- JSON sayıları `f64` (bkz. yukarı); FIX/ISO 20022/SWIFT ayrıştırıcıları yok; zaman dilimi/iş takvimi yok.
- Denetim izi için deterministik kayıt (append-only log, fsync), sabit zamanlı karşılaştırma, bellek sıfırlama (`zeroize`) yok.
- Düşük gecikme: `HashMap` hash ve ayırıcı davranışı belgelenmeli; lock-free halka tampon (SPSC/MPMC) std'de yok.

### Savunma/güvenlik
- Kripto yok, `std.tls` yalnızca istemci ve sistem kütüphanesine (OpenSSL/SChannel) bağlı: FIPS 140 / CNSA kullanımı için
  doğrulanmış modül seçimi, sabit zamanlı işlemler ve `zeroize` gerekli.
- `unsafe` envanteri aracı (`gg audit-unsafe`), bağımlılık hash kilidi var mı (`packages.py`) — doğrulanmadı; imzalı paket yok.
- Tedarik zinciri: `gg update` SHA-256 doğruluyor, imza (Sigstore/minisign) yok.

## 3. Yol haritası

**Faz 1: Sağlam temel (std'yi "adının hakkını verir" yap)** — önce bunu yap, her alan buna bağlı.
1. `std.math` tam libm + f32 + generic `min/max/clamp/abs` + tamsayı/bit işlemleri (`std.bits`). Kabul: C99 `<math.h>` ile fark testi.
2. `std.fs`/`std.io`: `Result[T, IoError]` (hata türü: NotFound, Permission, …), `Reader`/`Writer` feature'ları, stdin/stdout, ikili I/O,
   metadata, atomik yazma, dizin gezme. Eski `Optional/bool` API'leri `gg fix` ile taşınsın.
3. `std.thread`: `RwLock`, `Semaphore`, `Barrier`, `Once`, `try_lock`, zaman aşımlı bekleme, generic `Channel[T]` (+sınırlı/sınırsız), `Atomic` adlandırma birliği.
4. `std.time`: `Duration`, saat dilimi (IANA verisi), `DateTime` biçimleme/ayrıştırma, takvim aritmetiği.
5. `std.collections`: `BitSet`, `SortedSet`, `RingBuffer`; **heap'siz** `FixedVec[T, N]`, `FixedString[N]`, `FixedMap[K,V,N]`; kararlı sıralama.
6. `std.string` yinelenen API'yi kaldır (deprecate); `std.unicode` ekle.
7. ML modüllerini `gg-ml` paketine taşı; std'de `std.sock` private yap.
8. Her std modülü için: public API başına en az bir test, `no_std` uyumluluk etiketi (`gg api` çıktısına `no_std: yes/no/alloc` sütunu).

**Faz 2: Gömülü/gerçek zamanlı**
1. `@interrupt`, `@section`, `@inline`, `@naked`, `@used`, `@export_c` + linker script/başlangıç kodu (`gg new --target cortex-m4` şablonu, çalışan blinky QEMU'da test).
2. `mmio` tipli kayıtlar + bit-field + SVD'den üretici.
3. Özel `panic_handler`, `--panic=abort|handler`, `--forbid-heap`, `--forbid-recursion`, `gg stack-usage`.
4. `i128/u128`, `f16`, sabit nokta türü; QEMU (Cortex-M, RISC-V) CI'da.
5. `std.packet`'e BE imzalı/float, CRC, bit-alanı; `std.serial`, `std.can` (hal trait'leri: `embedded-hal` benzeri).

**Faz 3: Finans + güvenlik**
1. `Decimal`, `BigInt`, `Money`; JSON'da tamsayı/ondalık hassasiyetli sayı.
2. `std.crypto` (SHA-2/3, HMAC, HKDF, AES-GCM, ChaCha20-Poly1305, Ed25519/X25519), sabit zamanlı, `zeroize`; test vektörleri (Wycheproof/NIST CAVP).
3. `std.tls` sunucu + mTLS + pinning; IPv6, epoll/kqueue/IOCP.
4. `std.base64/hex/compress/csv/toml/uuid/log`.

**Faz 4: Havacılık/savunma güvencesi**
1. Safety profili (`gg check --profile safety`): `unsafe` yok, panic yok, özyineleme yok, heap yok, sınırlı döngü; ihlal listesi JSON.
2. Kapsama (satır/dal/MC/DC), `gg fuzz`, özellik tabanlı test, `assert_eq`/`require` ailesi.
3. Tekrarlanabilir derleme doğrulaması, SBOM, imzalı sürüm, `unsafe` denetim raporu.
4. Deterministik float modu + platformlar arası bit-bit test.
5. Sertifikasyon dokümanları: dil alt kümesi spesifikasyonu, gereksinim izlenebilirliği (conformance → SPEC maddeleri).
6. 1.0 kararlılık kilidi (API lock zaten var, `docs/STABILITY.md`) ve self-host'u yeniden değerlendirme (Python derleyici nitelendirilemez).

**Faz 5: Alan kütüphaneleri (ayrı paketler)** — `gg-linalg` (matris, kuaterniyon, Kalman, PID), `gg-dsp` (FFT, filtreler),
`gg-geo` (WGS84, ENU/ECEF, harita projeksiyonları), `gg-protocols` (ARINC 429/664, MIL-STD-1553, CCSDS, MAVLink, FIX),
`gg-units` (boyut analizli birimler).

## 4. Hemen başlanacak en yüksek getirili 5 iş
1. `std.math` + `std.bits` tamamlama (küçük, her alana yarar).
2. `std.fs/io` hata türlü yeniden tasarımı (`IoError`) ve `Reader/Writer`.
3. `FixedVec/FixedString` + `no_std` etiketi (gömülü/havacılığın kapısı).
4. `i128/u128` + `Decimal` (finansın kapısı).
5. `@interrupt/@section` + linker script + QEMU'da çalışan Cortex-M örneği (gömülü iddiasının kanıtı).

## 5. Durum (uygulama sonrası)

Bu bölüm planın ne kadarının yapıldığını dürüstçe listeler. Ayrıntı için `CHANGELOG.md` ("Unreleased").

**Yapıldı ve testle doğrulandı:** Faz 1'in çoğu (math, io/fs, thread, time, collections, `std.bits`, `std.heapless`, `std.unicode`, `no_std` etiketi);
Faz 2'nin dil tarafı (`@interrupt`/`@section`/..., `--forbid-heap`/`--forbid-recursion`/`--max-stack`, `i128`/`f16`, `std.mmio`/`std.hal`,
fonksiyon adreslerinin sabitlerde kullanılması: vektör tabloları, 32 bit hedeflerde C `size_t` uyumu); Faz 3'ün kütüphane tarafı (`Decimal`, `BigInt`,
`std.crypto`/`hash`/`encoding`/`compress`/`csv`/`toml`/`uuid`/`log`, `std.audit`, `std.fix`, kilitsiz SPSC kuyruk); Faz 4'ün araçları (`--profile safety`,
`gg coverage` (MC/DC), `gg fuzz`, `gg sbom`, `gg repro`, `gg unsafe-audit`, deterministik float + `std.dmath`, `docs/TRACEABILITY.md`);
Faz 5'in ilk sürümleri (`packages/gg-units`, `gg-linalg`, `gg-geo`, `gg-dsp`, `gg-protocols`).

**Yazıldı ama çalıştırılmadı (bu makinede araç yok):** `.github/workflows/embedded.yml` (clang/ARM/QEMU gerekir), `release.yml` içindeki Sigstore imzalama adımları,
32 bit hedeflerin gerçek çalıştırması (yalnız üretilen IR denetlendi), `docs/RTOS.md` örnekleri (donanımda/simülatörde denenmedi). Windows dışı
hedeflerde (macOS, Linux ARM) yalnız CI'nın sonucuna güvenilebilir.

**Yapılmadı:**
- Faz 1: ML modülleri `gg-ml` paketine taşınmadı; bunun yerine std'den silindi (`std.llama`, `std.tensor`, `std.nn`, `std.gguf`, `std.kquant`, `std.tokenizer`, `std.sampler`); `std.sock` private yapılmadı
  (`std.net` belgeleri `Poller` ile birlikte onu kullanıcıya gösteriyor); her public API için test şartı yalnız yeni modüller için sağlandı.
- Faz 2: `usize`'ın hedefin işaretçi genişliğine bağlanması (iç gösterim hâlâ 64 bit; yalnız C sınırında daraltılıyor); `gg new --target cortex-m4` şablonu;
  QEMU'da çalışan test (yukarıya bakın); `std.serial`/`std.can`; RTOS için hazır bağlamalar (yalnız belge).
- Faz 3: TLS sunucu tarafı, mTLS, sertifika sabitleme; epoll/kqueue/IOCP; ISO 20022; genel (MPMC) kilitsiz halka tamponu; `zeroize` iyileştirmeleri.
- Faz 4: gereksinim düzeyinde (yalnız bölüm düzeyinde değil) izlenebilirlik; araç nitelendirme; 1.0 kararlılık kilidi ve self-host kararı (bunlar
  proje sahibinin kararıdır, kod işi değildir).
- Faz 5: ARINC 664 (AFDX), harita projeksiyonları, jeoit/manyetik sapma, genişletilmiş/unscented Kalman.
