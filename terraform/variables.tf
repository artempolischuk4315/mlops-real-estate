variable "aws_region" {
  description = "Регіон AWS для розгортання"
  type        = string
  default     = "eu-north-1" # Stockholm
}

variable "account_id" {
  description = "ID AWS акаунту"
  type        = string
  default     = "921775433712"
}

variable "project_name" {
  description = "Загальна назва проекту"
  type        = string
  default     = "mlops-real-estate"
}
