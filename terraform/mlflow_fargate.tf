resource "aws_ecr_repository" "mlflow_ecr_repo" {
  name = "mlflow-server-${var.project_name}"
}

resource "aws_iam_role" "ecs_task_role" {
  name = "mlflow-ecs-task-role-${var.project_name}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_policy" "ecs_s3_policy" {
  name   = "mlflow-ecs-s3-policy-${var.project_name}"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Effect   = "Allow"
        Resource = [
          aws_s3_bucket.target_bucket.arn,
          "${aws_s3_bucket.target_bucket.arn}/mlflow_artifacts/*"
        ]
      }
    ]
  })
}

resource "null_resource" "build_push_mlflow_image" {
  triggers = {
    docker_file = filesha1("${path.module}/../mlflow_server/Dockerfile")
  }

  provisioner "local-exec" {
    command = <<EOF
      # Логін в ECR
      aws ecr get-login-password --region ${var.aws_region} | docker login --username AWS --password-stdin ${var.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com

      # Білд образу
      docker build --platform linux/amd64 -t ${aws_ecr_repository.mlflow_ecr_repo.repository_url}:latest ${path.module}/../mlflow_server/

      # Пуш в ECR
      docker push ${aws_ecr_repository.mlflow_ecr_repo.repository_url}:latest
    EOF
  }

  depends_on = [aws_ecr_repository.mlflow_ecr_repo]
}

resource "aws_iam_role_policy_attachment" "ecs_s3_attach" {
  role       = aws_iam_role.ecs_task_role.name
  policy_arn = aws_iam_policy.ecs_s3_policy.arn
}

resource "aws_iam_role" "ecs_execution_role" {
  name = "mlflow-ecs-execution-role-${var.project_name}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution_attach" {
  role       = aws_iam_role.ecs_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_ecs_cluster" "mlflow_cluster" {
  name = "mlflow-cluster-${var.project_name}"
}

resource "aws_security_group" "fargate_sg" {
  name   = "mlflow-fargate-sg-${var.project_name}"
  vpc_id = aws_vpc.mlops_vpc.id

  ingress {
    description = "Allow MLflow UI access from LB"
    from_port   = 5000
    to_port     = 5000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "Allow ECR Endpoint traffic from Fargate (self)"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    self        = true
  }

  egress {
    description     = "Allow egress to RDS"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.rds_sg.id] 
  }

  egress {
    description = "Allow egress to ECR Endpoints (self)"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    self        = true # Дозволяє трафік ДО ЦІЄЇ Ж ГРУПИ
  }

  egress {
    description = "Allow egress to S3 Gateway"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    prefix_list_ids = [data.aws_prefix_list.s3.id]
  }
}

data "aws_prefix_list" "s3" {
  filter {
    name   = "prefix-list-name"
    values = ["com.amazonaws.${var.aws_region}.s3"]
  }
}

resource "aws_security_group" "lb_sg" {
  name   = "mlflow-lb-sg-${var.project_name}"
  vpc_id = aws_vpc.mlops_vpc.id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_lb" "mlflow_lb" {
  name               = "mlflow-lb-${var.project_name}"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.lb_sg.id]
  subnets            = [aws_subnet.public_subnet_a.id, aws_subnet.public_subnet_b.id]
}

resource "aws_lb_target_group" "mlflow_tg" {
  name        = "mlflow-tg-${var.project_name}"
  port        = 5000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.mlops_vpc.id
  target_type = "ip"
  
  health_check {
    path = "/health"
  }
}

resource "aws_lb_listener" "mlflow_listener" {
  load_balancer_arn = aws_lb.mlflow_lb.arn
  port              = "80"
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.mlflow_tg.arn
  }
}

resource "aws_cloudwatch_log_group" "mlflow_log_group" {
  name = "/ecs/mlflow"

  retention_in_days = 7

  tags = {
    Name    = "mlflow-ecs-log-group"
    Project = var.project_name
  }
}

resource "aws_ecs_task_definition" "mlflow_task" {
  family                   = "mlflow-task-${var.project_name}"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "1024" # 1 vCPU
  memory                   = "2048" # 2 GB RAM
  execution_role_arn       = aws_iam_role.ecs_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([
    {
      name      = "mlflow"
      image     = "${aws_ecr_repository.mlflow_ecr_repo.repository_url}:latest"
      portMappings = [
        {
          containerPort = 5000
          hostPort      = 5000
        }
      ]
      # Команда запуску
      command = [
        "mlflow", "server",
        "--host", "0.0.0.0",
        "--port", "5000",
        "--backend-store-uri", "postgresql://${aws_db_instance.mlflow_db.username}:${random_string.db_password.result}@${aws_db_instance.mlflow_db.address}/${aws_db_instance.mlflow_db.db_name}",
        "--default-artifact-root", "s3://${aws_s3_bucket.target_bucket.id}/mlflow_artifacts/"
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = "/ecs/mlflow"
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "mlflow_service" {
  name            = "mlflow-service-${var.project_name}"
  cluster         = aws_ecs_cluster.mlflow_cluster.id
  task_definition = aws_ecs_task_definition.mlflow_task.arn
  launch_type     = "FARGATE"
  desired_count   = 1

  network_configuration {
    subnets         = [aws_subnet.private_subnet_a.id, aws_subnet.private_subnet_b.id]
    security_groups = [aws_security_group.fargate_sg.id]
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.mlflow_tg.arn
    container_name   = "mlflow"
    container_port   = 5000
  }

  depends_on = [aws_lb_listener.mlflow_listener]
}

output "mlflow_tracking_url" {
  description = "Публічний URL вашого MLflow Tracking Server"
  value       = "http://${aws_lb.mlflow_lb.dns_name}"
}
