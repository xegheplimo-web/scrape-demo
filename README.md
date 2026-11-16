# scrape-demo — Tool cào dữ liệu thương mại (bản demo)

Scraper Python "lịch sự" (polite crawler): tôn trọng `robots.txt`, delay giữa các
request, retry/backoff khi lỗi mạng, log xoay vòng, test offline — kèm adapter
mẫu cho `books.toscrape.com` (site công khai dành cho việc luyện cào dữ liệu).
Chỉ dùng `requests` + `beautifulsoup4`, không dependency nặng.

## Tính năng

- CLI: `python scrape.py --url <url> --out data.csv [--pages N]`
- Kiến trúc adapter: hỗ trợ nhiều site, mỗi site 1 module trong `sites/`
- Polite crawling: `User-Agent` rõ ràng, delay 1s giữa các request, timeout 20s
- `robots.txt`: **từ chối chạy** nếu URL bị disallow; HTTP 404 / unreachable →
  coi như allow-all (ghi WARNING trong log)
- Retry tối đa 3 lần, backoff mũ (1s → 2s → 4s) khi lỗi mạng, HTTP 429 hoặc 5xx;
  lỗi 4xx không retry
- `scrape.log` xoay vòng (tối đa 1MB × 3 file), mức INFO; cuối mỗi lần chạy in
  tóm tắt: số trang, số dòng, thời gian
- Chống vòng lặp pagination (dừng khi gặp URL đã crawl)

## Cài đặt

Yêu cầu Python 3.10+.

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows — macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

## Chạy thử

```bash
python scrape.py --url https://books.toscrape.com --pages 2 --out data.csv
```

Kết quả mẫu (output thật):

```
Scrape complete
  pages fetched : 2
  records       : 40
  output        : data.csv
  elapsed       : 4.4s
  log           : scrape.log
```

`data.csv` (2 trang × 20 sách, cắt đầu file):

```
title,price,availability,rating,url
A Light in the Attic,51.77,In stock,3,https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html
Tipping the Velvet,53.74,In stock,1,https://books.toscrape.com/catalogue/tipping-the-velvet_999/index.html
Soumission,50.10,In stock,1,https://books.toscrape.com/catalogue/soumission_998/index.html
```

Mỗi dòng log request ghi rõ trạng thái retry, ví dụ:

```
INFO  GET https://books.toscrape.com -> 200 (51294 bytes, attempt 1, no retry)
WARNING GET ... attempt 1/4 failed: ConnectTimeout — retrying in 1s   # khi có lỗi mạng
```

## Test

```bash
python -m pytest -q
# 17 passed — test parse trên HTML lưu sẵn + test retry/robots/delay, không gọi mạng
```

## Cấu trúc

```
scrape.py               CLI + lõi Scraper (fetch, retry, robots, delay, log, CSV)
sites/__init__.py       registry adapter theo domain
sites/books.py          adapter books.toscrape.com
tests/                  test offline (fixture HTML lưu sẵn, FakeSession)
tests/fixtures/         HTML mẫu tải 1 lần, commit kèm
requirements.txt        requests, beautifulsoup4, pytest
```

## Giới hạn (đọc trước khi chào khách)

- **Site cần login, captcha, hoặc render bằng JavaScript (SPA)**: tool này không
  xử lý — cần Playwright/Selenium ở phiên bản trả phí.
- **Site mới**: cần viết adapter riêng (`parse_records` + `next_page_url` +
  `FIELDS`), phần lõi fetch/retry/robots dùng lại nguyên.
- Không proxy rotation, không bypass anti-bot — đúng thiết kế "polite crawler".
- `robots.txt` unreachable hoặc trả 5xx → tạm coi như allow-all (WARNING trong
  log); site có rule chặn thật sẽ bị chặn đúng ở tầng `can_fetch`.
- Format `price`/`rating` được chuẩn hoá theo từng adapter (ví dụ books:
  `£51.77` → `51.77`, rating 1–5).
