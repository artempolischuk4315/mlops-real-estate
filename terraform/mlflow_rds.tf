resource "aws_security_group" "rds_sg" {
  name        = "mlflow-rds-sg-${var.project_name}"
  description = "Allows inbound Postgres traffic"
  vpc_id      = aws_vpc.mlops_vpc.id

  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [aws_vpc.mlops_vpc.cidr_block] # Дозволяємо зсередини VPC
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_db_subnet_group" "mlflow_rds_subnet_group" {
  name       = "mlflow-rds-subnet-group"
  subnet_ids = [aws_subnet.private_subnet_a.id, aws_subnet.private_subnet_b.id] # Розміщуємо в приватній підмережі
}

resource "random_string" "db_password" {
  length  = 16
  special = false
}

resource "aws_db_instance" "mlflow_db" {
  identifier           = "mlflow-db-${var.project_name}"
  allocated_storage    = 20
  storage_type         = "gp2"
  engine               = "postgres"
  engine_version       = "13"
  instance_class       = "db.t3.micro" # (Достатньо для Free Tier)
  db_name              = "mlflow_db"
  username             = "mlflow_user"
  password             = random_string.db_password.result
  db_subnet_group_name = aws_db_subnet_group.mlflow_rds_subnet_group.name
  vpc_security_group_ids = [aws_security_group.rds_sg.id]
  skip_final_snapshot  = true
  publicly_accessible  = false # Недоступна ззовні, тільки з VPC
}

output "db_password" {
  value     = random_string.db_password.result
  sensitive = true
}

output "db_host" {
  value = aws_db_instance.mlflow_db.address
}
