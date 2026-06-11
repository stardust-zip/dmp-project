## Plan phase Feature Engineering

Mục tiêu của phase này là biến `gold/validated_v2.parquet` từ **observation dataset** thành **training dataset** có thể dùng cho LightGBM, XGBoost, RandomForest.

### 1. Tạo module Feature Engineering

Tạo file:

```text
forecasting_module/feature_engineering.py
```
Input:

```text
gold/validated_v2.parquet
```

Output:

```text
feature_store/features.parquet
```

---

### 2. Thiết kế cấu hình

Module cần hỗ trợ các tham số:

```python
history_window_days = 30
forecast_horizon_hours = 24  # hoặc 168
weather_mode = "none"        # none | historical | forecast
```

Ý nghĩa:

```text
none        → Energy Only
historical  → Energy + Historical Weather
forecast    → Energy + Forecast Weather
```

---

### 3. Tạo calendar features

Từ `timestamp` sinh:

```text
hour
day_of_week
month
is_weekend
```

---

### 4. Tạo consumption features

Theo từng `building_id`:

```text
lag_1h
lag_24h
lag_168h
rolling_mean_24h
rolling_std_24h
rolling_mean_168h
rolling_std_168h
```

Các feature này chỉ dùng dữ liệu quá khứ để tránh data leakage.

---

### 5. Tạo metadata features

Giữ lại:

```text
primaryspaceusage
sqm
timezone
```

`primaryspaceusage` để dạng categorical, sau này cho model encode.

---

### 6. Tạo weather features theo mode

#### Mode 1: Energy Only

Không thêm weather.

#### Mode 2: Historical Weather

Dùng weather tại thời điểm `t`:

```text
airTemperature
dewTemperature
windDirection
windSpeed
```

#### Mode 3: Forecast Weather

Dùng weather tại thời điểm target:

```text
future_airTemperature = airTemperature.shift(-horizon)
future_dewTemperature = dewTemperature.shift(-horizon)
future_windDirection = windDirection.shift(-horizon)
future_windSpeed = windSpeed.shift(-horizon)
```

---

### 7. Tạo target

Với horizon bất kỳ:

```text
target = consumption.shift(-forecast_horizon_hours)
```

Ví dụ:

```text
horizon = 24  → dự báo cùng giờ ngày mai
horizon = 168 → dự báo cùng giờ tuần sau
```

---

### 8. Xử lý null sau feature engineering

Drop các dòng không đủ feature hoặc target:

```text
target is null
lag_24h is null
lag_168h is null
rolling_mean_24h is null
```

Nếu `weather_mode = forecast`, drop thêm:

```text
future_airTemperature is null
future_dewTemperature is null
future_windSpeed is null
future_windDirection is null
```

---

### 9. Lưu feature store

Output nên lưu theo mode/horizon:

```text
feature_store/features_h24_energy.parquet
feature_store/features_h24_historical_weather.parquet
feature_store/features_h24_forecast_weather.parquet
feature_store/features_h168_energy.parquet
...
```

---

### 10. Acceptance Criteria

Phase này hoàn thành khi:

```text
1. Tạo được feature dataset từ Gold v2.
2. Hỗ trợ 3 mode: Energy Only, Historical Weather, Forecast Weather.
3. Hỗ trợ horizon 24h và 168h.
4. Không có data leakage trong lag/rolling/target.
5. Feature dataset không còn null ở các cột bắt buộc để train.
6. Có report số dòng trước/sau drop null.
7. Output parquet sẵn sàng cho phase train/val/test.
```

Tóm lại: phase này sẽ tạo lớp **Feature Store** nằm giữa `Gold v2` và `Model Training`.
