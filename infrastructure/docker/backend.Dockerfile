FROM eclipse-temurin:21-jdk AS build
WORKDIR /src
COPY .mvn .mvn
COPY mvnw pom.xml ./
RUN --mount=type=cache,target=/root/.m2 ./mvnw -q -B dependency:go-offline
COPY src src
RUN --mount=type=cache,target=/root/.m2 ./mvnw -q -B package -DskipTests \
    && cp target/scm-backend-*.jar /src/app.jar

FROM eclipse-temurin:21-jre
# pebble ships with the Ubuntu base, is never run here, and carries Go stdlib CVEs
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* /usr/bin/pebble \
    && useradd --system --uid 10001 --no-create-home scm
COPY --from=build /src/app.jar /app/app.jar
USER 10001
# 8080 public API, 8081 health and metrics (never exposed publicly)
EXPOSE 8080 8081
HEALTHCHECK --interval=10s --timeout=3s --start-period=60s --retries=12 \
    CMD curl -fsS http://localhost:8081/actuator/health || exit 1
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75", "-jar", "/app/app.jar"]
