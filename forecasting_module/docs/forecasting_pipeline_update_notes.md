# Forecasting Pipeline - Góp ý cho bản cập nhật tiếp theo

Tài liệu này tổng hợp các điểm nên cải thiện cho pipeline forecasting, dựa trên code hiện tại và chiến lược xử lý missing data trong `handling_missing_data.md`.

## 1. Cập nhật chiến lược xử lý missing cho electricity

Hiện tại `Preprocessor.handle_missing_consumption()` chỉ xử lý:

- Gap `<= 6h`: linear interpolation.
- Gap `> 6h`: giữ nguyên null.

Theo `handling_missing_data.md`, nên mở rộng thành:

| Điều kiện | Xử lý đề xuất |
| --- | --- |
| Missing rate của building `> 30%` | Drop building |
| Gap `<= 6h` | Linear interpolation |
| `6h < gap <= 24h` | Seasonal imputation bằng giá trị `t-24h` |
| Gap `> 24h` | Giữ NaN và loại bỏ training window liên quan |

Điểm cần sửa:

- Thêm bước tính missing rate theo từng `building_id`.
- Loại bỏ building có missing rate quá cao trước khi tạo training dataset.
- Với gap từ 7 đến 24 giờ, không nên bỏ luôn; nên thử điền bằng giá trị cùng giờ của ngày trước đó.
- Với gap dài hơn 24 giờ, giữ null để downstream training loại bỏ window bị ảnh hưởng.

## 2. Cập nhật chiến lược xử lý missing cho weather

Hiện tại `Preprocessor.clean_weather()` đang dùng:

```python
pl.col(c).forward_fill().over("site_id")
```

Cách này chưa đúng với chiến lược trong `handling_missing_data.md`, vì forward-fill có thể kéo giá trị cũ qua một gap dài và làm sai đặc trưng thời tiết.

Nên đổi sang:

| Điều kiện | Xử lý đề xuất |
| --- | --- |
| Gap `<= 6h` | Linear interpolation |
| `6h < gap <= 24h` | Seasonal imputation bằng `t-24h` hoặc `t+24h` |
| Gap `> 24h` | Median theo `(site_id, month, hour)` |

Điểm cần sửa:

- Bỏ forward-fill không giới hạn.
- Tính gap null liên tiếp cho từng `site_id` và từng cột weather.
- Dùng linear interpolation cho gap ngắn.
- Dùng giá trị cùng giờ ngày trước hoặc ngày sau cho gap trung bình.
- Dùng median theo `site_id`, `month`, `hour` cho gap dài.

## 3. Cập nhật chiến lược xử lý metadata

Metadata không phải dữ liệu chuỗi thời gian nên không áp dụng interpolation.

Theo `handling_missing_data.md`, các feature quan trọng nên được xử lý như sau:

| Feature trong hướng dẫn | Cột tương ứng trong pipeline | Xử lý đề xuất |
| --- | --- | --- |
| `primary_use` | `primaryspaceusage` | Drop building nếu thiếu |
| `square_feet` | `sqm` | Drop building nếu thiếu hoặc không hợp lệ |


Điểm cần sửa:

- Validate `primaryspaceusage` không null.
- Validate `sqm` không null và `> 0`.
- Nếu building thiếu metadata quan trọng, nên drop building khỏi training dataset thay vì để null đi tiếp vào model.

## 4. Thêm weather vào validation schema

Weather là feature quan trọng cho forecasting, nhưng hiện tại `DataValidator.REQUIRED_COLUMNS` chưa yêu cầu các cột weather.

Nên tách schema thành:

```python
REQUIRED_BASE_COLUMNS = {
    "timestamp": pl.Datetime,
    "building_id": pl.Utf8,
    "consumption": pl.Float64,
    "site_id": pl.Utf8,
    "primaryspaceusage": pl.Utf8,
    "sqm": pl.Float64,
}

REQUIRED_WEATHER_COLUMNS = {
    "airTemperature": pl.Float64,
    "cloudCoverage": pl.Float64,
    "dewTemperature": pl.Float64,
    "precipDepth1HR": pl.Float64,
    "seaLvlPressure": pl.Float64,
    "windDirection": pl.Float64,
    "windSpeed": pl.Float64,
}
```

Validation report nên nói rõ lỗi thuộc nhóm base schema hay weather schema.

## 5. Check dtype thật sự

`REQUIRED_COLUMNS` hiện có khai báo dtype, nhưng `_check_required_columns()` chỉ kiểm tra cột có tồn tại hay không.

Nên thêm check dtype:

- `timestamp` phải là datetime.
- `building_id`, `site_id`, `primaryspaceusage` phải là string.
- `consumption`, `sqm` và các cột weather phải là numeric.

Nếu dtype sai, đây nên là lỗi critical vì có thể làm model training fail hoặc làm feature bị hiểu sai.

## 6. Kiểm tra coverage sau merge

Sau khi merge electricity + metadata + weather, cần biết join có bị lỗi hay không.

Nên thêm các chỉ số:

- Số dòng electricity không match được metadata.
- Số dòng missing `site_id`.
- Số dòng không match được weather theo `timestamp + site_id`.
- Tỷ lệ null từng cột weather sau merge.
- Weather coverage theo `site_id`.
- Số building bị ảnh hưởng bởi missing metadata/weather.

Điểm này đặc biệt quan trọng vì weather phụ thuộc vào `site_id` từ metadata. Nếu metadata lỗi, weather join cũng lỗi theo.

## 7. Tách validation và training readiness

Gold `validated.parquet` không nhất thiết phải sạch 100% null. Một số null vẫn nên được giữ lại, nhất là:

- Gap electricity `> 24h`.
- Những training window bị ảnh hưởng bởi missing target dài.
- Trường hợp thiếu dữ liệu thật không nên tạo giả.

Vì vậy nên thêm một bước riêng để tạo training matrix:

```text
data/processed/forecasting/training/train_matrix.parquet
```

Training matrix nên:

- Drop building có missing rate electricity `> 30%`.
- Drop building thiếu `primaryspaceusage` hoặc `sqm`.
- Drop dòng có target `consumption` null.
- Loại bỏ các training window bị ảnh hưởng bởi gap electricity `> 24h`.
- Xử lý weather null theo chiến lược interpolation/seasonal/median.
- Tạo time features.
- Tạo lag/rolling features.
- Split train/validation/test theo thời gian.

## 8. Thêm validation report có cấu trúc

Hiện tại validation chủ yếu `print()` ra terminal. Nên ghi report có cấu trúc, ví dụ:

```text
data/processed/forecasting/gold/validation_report.md
```

Report nên gồm:

- Tên check.
- Trạng thái passed/failed.
- Mức độ: critical/warning/info.
- Chi tiết.
- Số dòng bị ảnh hưởng.
- Tỷ lệ bị ảnh hưởng.
- Auto-fix đã áp dụng hay chưa.

Các nhóm check nên có:

- Schema base.
- Schema weather.
- Dtype.
- Duplicate.
- Negative consumption.
- Timestamp range.
- Missing rate theo building.
- Missing rate theo cột.
- Weather coverage.
- Metadata coverage.
- Join coverage.

## 9. Phân loại lỗi critical/warning/auto-fixable

Hiện tại validation check fail vẫn có thể tiếp tục lưu Gold.

Nên phân loại:

- Critical: thiếu cột bắt buộc, sai dtype, timestamp ngoài range, thiếu weather feature bắt buộc, metadata join lỗi nặng.
- Warning: missingness cao nhưng vẫn xử lý được, weather coverage thấp một phần.
- Auto-fixable: duplicate, consumption âm, gap ngắn có thể interpolation.


## 10. Lưu null summary theo từng stage

Nên lưu summary null thành một file report ở từng stage:

- Bronze.
- Silver.
- Gold.
- Training matrix.

Các cột cần theo dõi:

- `consumption`.
- `airTemperature`.


Ngoài null rate theo cột, nên có thêm null rate theo `building_id` và theo `site_id`.


## Ưu tiên làm trước

Nên ưu tiên theo thứ tự:

1. Thay weather forward-fill bằng chiến lược interpolation/seasonal/median theo `handling_missing_data.md`.
2. Thêm xử lý electricity gap `6h < gap <= 24h` bằng seasonal imputation `t-24h`.
3. Drop building có missing rate electricity `> 30%`.
4. Thêm weather columns vào validation schema.
5. Thêm dtype check thật sự.
6. Thêm weather coverage, metadata coverage và join coverage checks.
7. Ghi `validation_report.md`.


