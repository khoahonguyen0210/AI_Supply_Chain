# ECS on Fargate, the same topology as the kind deployment (docs/kubernetes.md):
#   frontend  behind the load balancer, the only public entry
#   backend   API, job worker off, reached as http://backend:8080 through Service Connect
#   engine    the single stateful engine (agent tasks, approvals on EFS), http://engine:8001
#   worker    backend with the job worker on + its own stateless engine sidecar on 127.0.0.1,
#             scaled 1..N on CPU
#   seed      one-off task (aws ecs run-task) that loads the synthetic world, like the seed job
resource "aws_ecs_cluster" "main" {
  name = local.name

  setting {
    name  = "containerInsights"
    value = "enhanced"
  }

  service_connect_defaults {
    namespace = aws_service_discovery_http_namespace.main.arn
  }
}

resource "aws_service_discovery_http_namespace" "main" {
  name = local.name
}

locals {
  image = { for name, repo in aws_ecr_repository.image : name => "${repo.repository_url}:${var.image_tag}" }

  secret = aws_secretsmanager_secret.app.arn
  # libpq reads PGPASSWORD, so the engine's connection string carries no password
  db_conninfo = "host=${aws_db_instance.postgres.address} port=5432 dbname=scm user=scm sslmode=require"

  log = { for service, group in aws_cloudwatch_log_group.service : service => {
    logDriver = "awslogs"
    options = {
      awslogs-group         = group.name
      awslogs-region        = var.region
      awslogs-stream-prefix = service
    }
  } }

  backend_environment = concat([
    { name = "POSTGRES_HOST", value = aws_db_instance.postgres.address },
    { name = "POSTGRES_PORT", value = "5432" },
    { name = "POSTGRES_DB", value = "scm" },
    { name = "POSTGRES_USER", value = "scm" },
    { name = "JAVA_TOOL_OPTIONS", value = "-XX:MaxRAMPercentage=70" },
    { name = "SCM_SECURITY_TRUSTFORWARDEDFOR", value = "true" },
    ], flatten([for i, user in [
      ["planner", "Pat Planner", "planner"],
      ["manager", "Mia Manager", "procurement_manager"],
      ["finance", "Fin Finance", "finance"],
      ["admin", "Ada Admin", "admin"],
      ] : [
      { name = "SCM_SECURITY_BOOTSTRAPUSERS_${i}_USERID", value = user[0] },
      { name = "SCM_SECURITY_BOOTSTRAPUSERS_${i}_DISPLAYNAME", value = user[1] },
      { name = "SCM_SECURITY_BOOTSTRAPUSERS_${i}_ROLE", value = user[2] },
  ]]))

  backend_secrets = concat([
    { name = "POSTGRES_PASSWORD", valueFrom = "${local.secret}:POSTGRES_PASSWORD::" },
    { name = "SCM_JWT_SECRET", valueFrom = "${local.secret}:SCM_JWT_SECRET::" },
    { name = "SCM_ML_INTERNAL_TOKEN", valueFrom = "${local.secret}:SCM_ML_INTERNAL_TOKEN::" },
    ], [for i in range(4) :
    { name = "SCM_SECURITY_BOOTSTRAPUSERS_${i}_PASSWORD", valueFrom = "${local.secret}:SCM_DEMO_PASSWORD::" }
  ])

  engine_environment = [
    { name = "SCM_ML_KNOWLEDGE_DATABASE_URL", value = local.db_conninfo },
    { name = "SCM_ML_EMBEDDER", value = "fastembed" },
    { name = "SCM_ML_PLANNER", value = var.planner },
  ]

  engine_secrets = concat([
    { name = "PGPASSWORD", valueFrom = "${local.secret}:POSTGRES_PASSWORD::" },
    { name = "SCM_ML_INTERNAL_TOKEN", valueFrom = "${local.secret}:SCM_ML_INTERNAL_TOKEN::" },
    ], var.planner == "claude" ? [
    { name = "ANTHROPIC_API_KEY", valueFrom = aws_secretsmanager_secret.anthropic.arn },
  ] : [])

  backend_health = {
    command     = ["CMD-SHELL", "curl -fsS http://localhost:8081/actuator/health || exit 1"]
    interval    = 10
    timeout     = 3
    retries     = 6
    startPeriod = 120
  }

  engine_health = {
    command     = ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=2)"]
    interval    = 10
    timeout     = 3
    retries     = 6
    startPeriod = 180
  }

  private_network = {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = false
  }
}

# --- load balancer ------------------------------------------------------------------------------

resource "aws_lb" "main" {
  name                       = local.name
  load_balancer_type         = "application"
  subnets                    = aws_subnet.public[*].id
  security_groups            = [aws_security_group.alb.id]
  drop_invalid_header_fields = true
  # copilot tasks run for tens of seconds behind the Next.js proxy
  idle_timeout = 120
}

resource "aws_lb_target_group" "frontend" {
  name                 = "${local.name}-frontend"
  port                 = 3000
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = aws_vpc.main.id
  deregistration_delay = 30

  health_check {
    path                = "/"
    matcher             = "200-399"
    interval            = 15
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = var.certificate_arn == "" ? "forward" : "redirect"
    target_group_arn = var.certificate_arn == "" ? aws_lb_target_group.frontend.arn : null

    dynamic "redirect" {
      for_each = var.certificate_arn == "" ? [] : [1]
      content {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }
  }
}

resource "aws_lb_listener" "https" {
  count             = var.certificate_arn == "" ? 0 : 1
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend.arn
  }
}

# --- task definitions ---------------------------------------------------------------------------

resource "aws_ecs_task_definition" "frontend" {
  family                   = "${local.name}-frontend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.frontend.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name         = "frontend"
    image        = local.image["scm-frontend"]
    essential    = true
    portMappings = [{ name = "http", containerPort = 3000, protocol = "tcp" }]
    # BACKEND_URL is baked in at build time (http://backend:8080), which Service Connect resolves
    logConfiguration = local.log["frontend"]
  }])
}

resource "aws_ecs_task_definition" "backend" {
  family                   = "${local.name}-backend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.backend.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name      = "backend"
    image     = local.image["scm-backend"]
    essential = true
    portMappings = [
      { name = "api", containerPort = 8080, protocol = "tcp", appProtocol = "http" },
      { name = "management", containerPort = 8081, protocol = "tcp" },
    ]
    environment = concat(local.backend_environment, [
      { name = "ML_SERVICE_URL", value = "http://engine:8001" },
      { name = "SCM_JOBS_WORKER_ENABLED", value = "false" },
    ])
    secrets          = local.backend_secrets
    healthCheck      = local.backend_health
    logConfiguration = local.log["backend"]
  }])
}

resource "aws_ecs_task_definition" "engine" {
  family                   = "${local.name}-engine"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 1024
  memory                   = 2048
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.engine.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  volume {
    name = "state"
    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.engine_state.id
      transit_encryption = "ENABLED"
      authorization_config {
        access_point_id = aws_efs_access_point.engine_state.id
        iam             = "ENABLED"
      }
    }
  }

  container_definitions = jsonencode([{
    name         = "engine"
    image        = local.image["scm-ml"]
    essential    = true
    portMappings = [{ name = "http", containerPort = 8001, protocol = "tcp", appProtocol = "http" }]
    environment = concat(local.engine_environment, [
      { name = "SCM_ML_STATE_PATH", value = "/var/lib/scm/engine-state.sqlite" },
    ])
    secrets          = local.engine_secrets
    mountPoints      = [{ sourceVolume = "state", containerPath = "/var/lib/scm" }]
    healthCheck      = local.engine_health
    logConfiguration = local.log["engine"]
  }])
}

# Backend with the job worker on, talking to its own engine sidecar over localhost (awsvpc tasks
# share one network namespace). Stateless: the sidecar keeps agent state in memory.
resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.name}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 2048
  memory                   = 4096
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.engine.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name      = "engine"
      image     = local.image["scm-ml"]
      essential = true
      environment = concat(local.engine_environment, [
        { name = "SCM_ML_HOST", value = "127.0.0.1" },
        { name = "SCM_ML_STATE_PATH", value = ":memory:" },
        { name = "OMP_NUM_THREADS", value = "1" },
        { name = "OPENBLAS_NUM_THREADS", value = "1" },
        { name = "MKL_NUM_THREADS", value = "1" },
      ])
      secrets          = local.engine_secrets
      healthCheck      = local.engine_health
      logConfiguration = local.log["worker"]
    },
    {
      name         = "worker"
      image        = local.image["scm-backend"]
      essential    = true
      dependsOn    = [{ containerName = "engine", condition = "HEALTHY" }]
      portMappings = [{ name = "management", containerPort = 8081, protocol = "tcp" }]
      environment = concat(local.backend_environment, [
        { name = "ML_SERVICE_URL", value = "http://127.0.0.1:8001" },
        { name = "SCM_JOBS_WORKER_ENABLED", value = "true" },
        { name = "SCM_JOBS_LEASE", value = "120s" },
      ])
      secrets          = local.backend_secrets
      healthCheck      = local.backend_health
      logConfiguration = local.log["worker"]
    },
  ])
}

resource "aws_ecs_task_definition" "seed" {
  family                   = "${local.name}-seed"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.engine.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name             = "seed"
    image            = local.image["scm-ml"]
    essential        = true
    command          = ["python", "-m", "scm_ml.synthetic.sql_export", "--database-url", local.db_conninfo]
    secrets          = [{ name = "PGPASSWORD", valueFrom = "${local.secret}:POSTGRES_PASSWORD::" }]
    logConfiguration = local.log["seed"]
  }])
}

# --- services -----------------------------------------------------------------------------------

resource "aws_ecs_service" "backend" {
  name                   = "backend"
  cluster                = aws_ecs_cluster.main.id
  task_definition        = aws_ecs_task_definition.backend.arn
  desired_count          = 1
  launch_type            = "FARGATE"
  enable_execute_command = false

  network_configuration {
    subnets          = local.private_network.subnets
    security_groups  = local.private_network.security_groups
    assign_public_ip = local.private_network.assign_public_ip
  }

  service_connect_configuration {
    enabled = true
    service {
      port_name = "api"
      client_alias {
        dns_name = "backend"
        port     = 8080
      }
    }
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
}

# Exactly one task: it owns the SQLite state on EFS (Recreate in Kubernetes).
resource "aws_ecs_service" "engine" {
  name                               = "engine"
  cluster                            = aws_ecs_cluster.main.id
  task_definition                    = aws_ecs_task_definition.engine.arn
  desired_count                      = 1
  launch_type                        = "FARGATE"
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100

  network_configuration {
    subnets          = local.private_network.subnets
    security_groups  = local.private_network.security_groups
    assign_public_ip = local.private_network.assign_public_ip
  }

  service_connect_configuration {
    enabled = true
    service {
      port_name = "http"
      client_alias {
        dns_name = "engine"
        port     = 8001
      }
    }
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [aws_efs_mount_target.engine_state]
}

resource "aws_ecs_service" "worker" {
  name            = "worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = var.worker_min
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = local.private_network.subnets
    security_groups  = local.private_network.security_groups
    assign_public_ip = local.private_network.assign_public_ip
  }

  # client only: resolves nothing it does not need, but keeps the namespace consistent
  service_connect_configuration {
    enabled = true
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  # the autoscaler owns the count after creation
  lifecycle {
    ignore_changes = [desired_count]
  }
}

resource "aws_ecs_service" "frontend" {
  name            = "frontend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.frontend.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = local.private_network.subnets
    security_groups  = local.private_network.security_groups
    assign_public_ip = local.private_network.assign_public_ip
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.frontend.arn
    container_name   = "frontend"
    container_port   = 3000
  }

  service_connect_configuration {
    enabled = true
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [aws_lb_listener.http]
}

# --- worker scaling -----------------------------------------------------------------------------
# CPU tracks queue pressure here because a worker is CPU-bound while it runs a job
# (docs/kubernetes.md measures that). Scaling on queue depth would need the backend's
# scm_jobs{status="QUEUED"} gauge exported to CloudWatch (an ADOT collector sidecar).

resource "aws_appautoscaling_target" "worker" {
  service_namespace  = "ecs"
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.worker.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = var.worker_min
  max_capacity       = var.worker_max
}

resource "aws_appautoscaling_policy" "worker_cpu" {
  name               = "${local.name}-worker-cpu"
  service_namespace  = aws_appautoscaling_target.worker.service_namespace
  resource_id        = aws_appautoscaling_target.worker.resource_id
  scalable_dimension = aws_appautoscaling_target.worker.scalable_dimension
  policy_type        = "TargetTrackingScaling"

  target_tracking_scaling_policy_configuration {
    target_value       = 60
    scale_out_cooldown = 60
    scale_in_cooldown  = 300

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}
