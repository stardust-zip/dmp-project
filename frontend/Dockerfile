FROM node:20-alpine

WORKDIR /app

# Prevents Docker from failing if package.json doesn't exist yet.
COPY package*.json ./
RUN if [ -f package.json ]; then npm install; fi

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
