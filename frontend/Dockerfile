FROM node:20-alpine AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .

# npm run build 는 tsc -b && vite build 다. 예전에는 tsc -b 와 lint 만 돌려서
# dist/ 가 생기지 않았고, 아래 COPY 단계가 빈 디렉터리를 집었다 (이슈 #128).
# lint 는 CI 가 돌린다. 이미지 빌드에서 다시 하면 시간만 두 배로 든다.
RUN npm run build

# 비root 로 돌기 위해 unprivileged 이미지를 쓴다. 기본 nginx 는 마스터가 root 이고
# 80 번 포트를 잡는데, 컨테이너 안에서 root 로 돌 이유가 없다.
# 이 이미지는 8080 을 듣는다 — docker-compose 의 포트 매핑도 함께 맞췄다.
FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
