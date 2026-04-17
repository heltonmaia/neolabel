FROM node:20-alpine

WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .

EXPOSE 5173
# --host 0.0.0.0 para o Vite aceitar conexões vindas de fora do container.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
