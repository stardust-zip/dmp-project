# Missing Value Handling Strategy

## Mục tiêu

Xử lý Missing Values cho bài toán dự báo điện năng tiêu thụ trên bộ dữ liệu Building Data Genome Project 2 (BDG2).

Dữ liệu được chia thành ba nhóm:

* Electricity Meter Data
* Weather Data
* Building Metadata

Nguyên tắc chung:

* Chỉ nội suy các khoảng thiếu ngắn.
* Tận dụng tính chu kỳ của dữ liệu thay vì sử dụng Mean Imputation.
* Không tạo dữ liệu giả cho các khoảng thiếu kéo dài.
* Loại bỏ các building có chất lượng dữ liệu quá thấp.

---

# 1. Electricity Meter Data

Dữ liệu điện năng có tính chu kỳ mạnh theo giờ trong ngày và theo ngày trong tuần. Tuy nhiên, mức tiêu thụ có thể thay đổi đáng kể do lịch vận hành, ngày nghỉ hoặc các sự kiện bất thường. Vì vậy cần hạn chế nội suy trên các khoảng thiếu dài.

| Điều kiện          | Xử lý                                               | Lý do                                                                  |
| ------------------ | --------------------------------------------------- | ---------------------------------------------------------------------- |
| Missing Rate > 30% | Drop Building                                       | Chất lượng dữ liệu không đủ để huấn luyện mô hình đáng tin cậy         |
| Gap ≤ 6h           | Linear Interpolation                                | Mức tiêu thụ điện thường thay đổi liên tục trong khoảng thời gian ngắn |
| 6h < Gap ≤ 24h     | Seasonal Imputation (t-24h)                         | Cùng một giờ ở các ngày liên tiếp thường có hành vi tiêu thụ tương tự  |
| Gap > 24h          | Giữ nguyên NaN và loại bỏ training window liên quan | Tránh tạo dữ liệu giả cho các khoảng mất dữ liệu kéo dài               |

### Ví dụ

```text
2025-01-10 14:00 bị thiếu

→ sử dụng giá trị tại
2025-01-09 14:00
```

---

# 2. Weather Data

Các biến thời tiết như nhiệt độ, áp suất hay tốc độ gió thường tuân theo quy luật biến thiên theo giờ trong ngày. Do đó việc sử dụng thông tin theo mùa vụ hiệu quả hơn các phương pháp điền giá trị trung bình.

| Điều kiện      | Xử lý                        | Lý do                                                                            |
| -------------- | ---------------------------- | -------------------------------------------------------------------------------- |
| Gap ≤ 6h       | Linear Interpolation         | Thời tiết thay đổi tương đối liên tục trong thời gian ngắn                       |
| 6h < Gap ≤ 24h | Seasonal Imputation (t±24h)  | Bảo toàn quy luật nhiệt độ và thời tiết theo chu kỳ ngày                         |
| Gap > 24h      | Median(site_id, month, hour) | Khôi phục giá trị dựa trên đặc trưng khí hậu của địa điểm và thời điểm tương ứng |

### Ví dụ

```text
Site = Panther
Month = July
Hour = 13:00
```

→ sử dụng:

```text
Median Temperature
(Panther, July, 13:00)
```

---

# 3. Building Metadata

Metadata không phải dữ liệu chuỗi thời gian nên không áp dụng nội suy. Các giá trị thiếu được xử lý dựa trên mức độ quan trọng của từng thuộc tính.

| Feature     | Xử lý                                | Lý do                                                     |
| ----------- | ------------------------------------ | --------------------------------------------------------- |
| primary_use | Drop Building                        | Đây là đặc trưng quan trọng phản ánh hành vi sử dụng điện |
| square_feet | Drop Building                        | Diện tích có tương quan mạnh với mức tiêu thụ điện        |
| year_built  | Median theo primary_use hoặc site_id | Giảm ảnh hưởng của giá trị ngoại lệ                       |
| floor_count | Median                               | Đặc trưng phụ, có thể thay thế bằng giá trị trung vị      |

---

# Summary

```text
Electricity Meter
├─ Missing Rate >30%
│  └─ Drop Building
├─ Gap ≤6h
│  └─ Linear Interpolation
├─ 6h < Gap ≤24h
│  └─ Seasonal Imputation (t-24h)
└─ Gap >24h
   ├─ Keep NaN
   └─ Remove affected training windows

Weather
├─ Gap ≤6h
│  └─ Linear Interpolation
├─ 6h < Gap ≤24h
│  └─ Seasonal Imputation (t±24h)
└─ Gap >24h
   └─ Median(site_id, month, hour)

Metadata
├─ primary_use
│  └─ Drop Building
├─ square_feet
│  └─ Drop Building
├─ year_built
│  └─ Median
└─ floor_count
   └─ Median
```
