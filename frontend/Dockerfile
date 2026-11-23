# Build the interface, then serve it with nginx, which also passes /api to the api container.
FROM node:22-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY trace-headers.conf /etc/nginx/trace-headers.conf
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 80
