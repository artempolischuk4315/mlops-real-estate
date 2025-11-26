1. export AWS_PROFILE=mlops-project-9217
2. run `terraform apply` 
2. When it failed - put model.tar.gz to S3 bucket mentioned in logs
3. run `terraform apply` again
4. Run via `aws s3 cp ../data/real_estate.csv s3://source-bucket-921775433712-mlops-real-estate/seed/real_estate.csv`
5. Data example to tun on Inference lambda - [[2013.583, 42, 55.87882, 10, 24.98298, 71.54024]]
6. On Monitoring {
  "force_today": true
} -> target-bucket/monitoring/reports/data_drift_report
7. 