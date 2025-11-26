resource "aws_vpc_endpoint" "ecr_api" {
  vpc_id              = aws_vpc.mlops_vpc.id
  service_name        = "com.amazonaws.${var.aws_region}.ecr.api"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true

  subnet_ids = [
    aws_subnet.private_subnet_a.id,
    aws_subnet.private_subnet_b.id
  ]
  
  security_group_ids = [aws_security_group.fargate_sg.id]
}

resource "aws_vpc_endpoint" "ecr_dkr" {
  vpc_id              = aws_vpc.mlops_vpc.id
  service_name        = "com.amazonaws.${var.aws_region}.ecr.dkr"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true

  subnet_ids = [
    aws_subnet.private_subnet_a.id,
    aws_subnet.private_subnet_b.id
  ]
  security_group_ids = [aws_security_group.fargate_sg.id]
}

resource "aws_vpc_endpoint" "s3_gateway" {
  vpc_id            = aws_vpc.mlops_vpc.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"

  route_table_ids = [
    aws_route_table.public_rt.id,
    aws_route_table.private_rt_for_s3.id
  ]
}

resource "aws_vpc_endpoint" "logs" {
  vpc_id              = aws_vpc.mlops_vpc.id
  service_name        = "com.amazonaws.${var.aws_region}.logs"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true

  subnet_ids = [
    aws_subnet.private_subnet_a.id,
    aws_subnet.private_subnet_b.id
  ]

  security_group_ids = [aws_security_group.fargate_sg.id]
}

resource "aws_route_table" "private_rt_for_s3" {
  vpc_id = aws_vpc.mlops_vpc.id

  tags = {
    Name = "mlops-private-rt-s3"
  }
}

resource "aws_route_table_association" "private_rt_assoc_a_s3" {
  subnet_id      = aws_subnet.private_subnet_a.id
  route_table_id = aws_route_table.private_rt_for_s3.id
}

resource "aws_route_table_association" "private_rt_assoc_b_s3" {
  subnet_id      = aws_subnet.private_subnet_b.id
  route_table_id = aws_route_table.private_rt_for_s3.id
}
