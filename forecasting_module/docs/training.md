# Phase 7 – Benchmark Training & Evaluation Notebook

## Mục tiêu

Xây dựng notebook huấn luyện, đánh giá và so sánh nhiều mô hình forecasting trên cùng một bộ dữ liệu Train / Validation / Test. Notebook được thiết kế để upload lên Google Colab và chạy trực tiếp.

---

## Input

```text
dataset/train.parquet
dataset/validation.parquet
dataset/test.parquet
```

Các file này được tạo từ Phase 6 – Dataset Builder.

---

## Deliverable chính

```text
notebooks/benchmark_training_evaluation.ipynb
```

---

## Công việc thực hiện

### 7.1. Chuẩn bị môi trường Colab

Notebook cần có cell cài đặt thư viện:

```text
polars
pandas
scikit-learn
xgboost
lightgbm
joblib
matplotlib
```

Nếu dữ liệu lưu trên Google Drive, notebook cần hỗ trợ mount Drive.

---

### 7.2. Load dataset

Đọc các file:

```text
train.parquet
validation.parquet
test.parquet
```

Kiểm tra:

```text
số dòng
số cột
danh sách feature
target
khoảng thời gian từng tập
```

---

### 7.3. Chuẩn bị Feature / Target

Tách:

```text
X_train, y_train
X_val, y_val
X_test, y_test
```

Xử lý categorical feature như:

```text
building_id
primaryspaceusage
timezone
```

Đảm bảo train / validation / test có cùng schema.

---

### 7.4. Huấn luyện mô hình benchmark

Huấn luyện tối thiểu các mô hình:

```text
Linear Regression
Random Forest
XGBoost
LightGBM
```

Mỗi mô hình được train trên cùng feature set, cùng target và cùng split để so sánh công bằng.

---

### 7.5. Đánh giá mô hình

Tính metric trên Validation và Test:

```text
MAE
RMSE
MAPE
SMAPE
```

Kết quả được lưu vào bảng leaderboard.

---

### 7.6. So sánh các feature mode

Notebook cần hỗ trợ chạy với các mode:

```text
Energy Only
Energy + Historical Weather
Energy + Forecast Weather
```

Mục tiêu là so sánh xem weather có cải thiện độ chính xác forecasting hay không.

---

### 7.7. Visualization trong notebook

Hiển thị trực tiếp trong notebook:

```text
Actual vs Predicted plot
Feature Importance plot
Metric comparison table
```

Không xuất report HTML.

---

### 7.8. Lưu kết quả

Lưu các artifact:

```text
models/linear_regression.pkl
models/random_forest.pkl
models/xgboost.pkl
models/lightgbm.pkl
models/best_model.pkl

report/model_leaderboard.csv
report/evaluation_summary.md
```

---

## Acceptance Criteria

* Notebook chạy được trên Google Colab.
* Load được Train / Validation / Test dataset từ Drive hoặc local path.
* Train được tối thiểu 4 mô hình benchmark.
* Tính được MAE, RMSE, MAPE, SMAPE trên Validation và Test.
* Tạo được leaderboard so sánh mô hình.
* Hiển thị được biểu đồ trong notebook.
* Không tạo report HTML.
* Lưu được best model và kết quả đánh giá.
