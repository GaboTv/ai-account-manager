FROM node:22-bookworm-slim
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
# Where the browser reaches the API. Baked in at build time (Next.js inlines
# NEXT_PUBLIC_* during `next build`). Behind a same-origin proxy, build with
# --build-arg NEXT_PUBLIC_API_URL=https://<host>/api
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build
EXPOSE 3000
# Production server. Local dev overrides with `command: npm run dev` in compose.
CMD ["npm", "start"]
