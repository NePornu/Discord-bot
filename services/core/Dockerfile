FROM golang:1.22-alpine AS builder

WORKDIR /app

# Install build dependencies
RUN apk add --no-cache git

# Copy go.mod and go.sum first to leverage Docker cache
COPY services/core/go.mod services/core/go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download && go mod tidy

# Copy the rest of the source code
COPY services/core .
COPY .env ../.env

# Build the Go app
RUN --mount=type=cache,target=/root/.cache/go-build \
    --mount=type=cache,target=/go/pkg/mod \
    CGO_ENABLED=0 GOOS=linux go build -o bot_go main.go

######## Start a new stage from scratch #######
FROM alpine:latest  

RUN apk --no-cache add ca-certificates tzdata

WORKDIR /root/

# Copy the Pre-built binary file from the previous stage
COPY --from=builder /app/bot_go .
COPY .env .

# Command to run the executable
CMD ["./bot_go"]
