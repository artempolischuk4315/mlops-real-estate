
resource "aws_s3_bucket" "source_bucket" {
  bucket = "source-bucket-${var.account_id}-${var.project_name}"
  force_destroy = true

  tags = {
    Name    = "Source Data Bucket"
    Project = var.project_name
  }
}

resource "aws_s3_bucket" "target_bucket" {
  bucket = "target-bucket-${var.account_id}-${var.project_name}"
  force_destroy = true 

  tags = {
    Name    = "ML Target Bucket - Artifacts and Data"
    Project = var.project_name
  }
}

resource "aws_s3_object" "seed_data" {
  bucket = aws_s3_bucket.source_bucket.id
  key    = "seed/real_estate.csv"
  
  source = "../data/real_estate.csv"
  
  etag = filemd5("../data/real_estate.csv")
}
