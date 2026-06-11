# Phase 6 – Dataset Builder (Train / Validation / Test)

## Mục tiêu

Xây dựng bộ dữ liệu huấn luyện chuẩn cho forecasting từ Feature Store, đảm bảo không xảy ra data leakage và sẵn sàng cho các phase Benchmark Training và Evaluation.

---

## Input

```text
feature_store/features.parquet
```

Bao gồm:

* Calendar Features
* Lag Features
* Rolling Features
* Metadata Features
* Weather Features (nếu có)
* Target

---

## Công việc thực hiện

### 6.1. Thiết kế chiến lược chia dữ liệu

Áp dụng Time-based Split thay vì Random Split.

Ví dụ:

```text
Train      : 2016-01 → 2017-06
Validation : 2017-07 → 2017-09
Test       : 2017-10 → 2017-12
```

Hoặc cấu hình theo tỷ lệ:

```text
Train      : 70%
Validation : 15%
Test       : 15%
```

theo thứ tự thời gian.

---

### 6.2. Xây dựng Dataset Builder

Tạo module:

```text
forecasting_module/dataset_builder.py
```

Chức năng:

* Đọc Feature Store
* Chia Train / Validation / Test
* Kiểm tra tính liên tục theo thời gian
* Xuất các tập dữ liệu riêng biệt

---

### 6.3. Kiểm tra Data Leakage

Đảm bảo:

```text
max(train_timestamp)
<
min(validation_timestamp)

max(validation_timestamp)
<
min(test_timestamp)
```

Không có mẫu dữ liệu tương lai xuất hiện trong tập Train.

---

### 6.4. Thống kê dữ liệu

Sinh báo cáo:

```text
dataset_summary.md
```

Bao gồm:

* Số lượng sample Train
* Số lượng sample Validation
* Số lượng sample Test
* Khoảng thời gian của từng tập
* Tỷ lệ phân chia

---

### 6.5. Xuất dữ liệu

Lưu:

```text
dataset/
├── train.parquet
├── validation.parquet
└── test.parquet
```

---

## Deliverables

```text
forecasting_module/dataset_builder.py

dataset/train.parquet
dataset/validation.parquet
dataset/test.parquet

report/dataset_summary.md
```

---

## Acceptance Criteria

* Chia dữ liệu hoàn toàn theo thời gian.
* Không sử dụng Random Split.
* Không xảy ra Data Leakage.
* Tạo thành công Train / Validation / Test dataset.
* Sinh báo cáo thống kê dữ liệu.
* Dataset sẵn sàng cho training