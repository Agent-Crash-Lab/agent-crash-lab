FROM eclipse-temurin:21-jdk AS build
WORKDIR /app

# 빌드 설정만 먼저 복사해 의존성을 받아 둔다. 소스만 바뀌면 이 단계는 캐시를 재사용한다.
COPY gradlew settings.gradle build.gradle ./
COPY gradle gradle
RUN --mount=type=cache,target=/root/.gradle ./gradlew dependencies --no-daemon -q > /dev/null

COPY src src
RUN --mount=type=cache,target=/root/.gradle ./gradlew bootJar --no-daemon -x test

FROM eclipse-temurin:21-jre
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build /app/build/libs/*.jar app.jar
# compose가 저장소의 fixtures/를 /fixtures에 마운트한다
ENV CRASHLAB_FIXTURES_DIR=/fixtures
EXPOSE 8081
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
