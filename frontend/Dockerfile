FROM node:22-bookworm-slim
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
# Where the browser reaches the API. Default: direct dev port. Behind the TLS
# proxy, build with --build-arg NEXT_PUBLIC_API_URL=https://localhost:8443/api
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
EXPOSE 3000
CMD ["npm", "run", "dev"]
