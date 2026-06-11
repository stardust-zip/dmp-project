# Phase 2: Outlier Detection

## Mục tiêu

Phát hiện các giá trị tiêu thụ điện bất thường do:

* Sensor lỗi
* Meter reset
* Lỗi truyền dữ liệu
* Spike không hợp lý

Sau khi phát hiện:

```text
Outlier
→ NaN
→ Chạy lại Missing Handling Pipeline
```

---

## Task 2.1: EDA Outlier Analysis

### Thực hiện

Phân tích theo:

* building_id
* site_id
* primaryspaceusage

Sinh báo cáo:

```text
report/outlier_summary.csv
```

### Deliverable

* Phân bố điện năng theo building
* Top 20 building có variance lớn nhất
* Histogram meter_reading
* Boxplot theo building type

---

## Task 2.2: Electricity Outlier Detection

### Rule

Thực hiện theo từng:

```text
building_id + hour_of_day
```

Sử dụng:

```text
Q1
Q3
IQR
```

Outlier:

```text
< Q1 - 3×IQR

> Q3 + 3×IQR
```

### Output

```text
electricity_outlier_report.csv
```

Bao gồm:

* building_id
* total_rows
* outlier_count
* outlier_rate

---

## Task 2.3: Weather Outlier Detection

### Rule-based

airTemperature:

```text
[-30°C, 60°C]
```

windSpeed:

```text
>= 0
```

cloudCoverage:

```text
[0, 10]
```

seaLvlPressure:

```text
[800, 1100]
```

Ngoài khoảng:

```text
→ NaN
```

---

## Task 2.4: Re-run Missing Pipeline

Sau khi Outlier → NaN

Chạy lại:

```text
Linear
Seasonal
Median
```

### Deliverable

```text
gold_dataset_v2.parquet
```

---

