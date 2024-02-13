FROM ubuntu:22.04

RUN apt-get update -y
RUN apt-get install -y curl xvfb protobuf-compiler
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash -
RUN apt-get install -y nodejs
# Extra packages are needed to build `gl` library on arm64 architecture (not needed on amd64 aka x86_64):
RUN test "$(arch)" = "x86_64" || apt-get install -y python-is-python3 pkg-config build-essential libxi-dev libglew-dev

RUN mkdir /pdb-images
WORKDIR /pdb-images

COPY package.json ./
RUN npm install

COPY src ./src
COPY tsconfig.json ./
RUN npm run build

RUN npm install -g .

RUN mkdir /xvfb
ENV XVFB_DIR="/xvfb"

RUN apt install -y python3-pip
RUN pip3 install grpcio-tools

RUN mkdir -p /pdb-images/protoc-gateway /pdb-images/protoc-openapi /pdb-images/proxy/gateway /pdb-images/proxy/app /pdb-images/openapi /pdb-images/bin /pdb-images/out

COPY ["service/main.go", "./proxy/"]
COPY ["service/compile_protobuf.sh", "service/meshservice/meshservice.proto", "service/meshservice/mesh-service-server.py", "./"]
COPY ["service/google/", "./google/"]
COPY ["service/protoc-gen-openapiv2/", "./protoc-gen-openapiv2/"]

ENV PATH="${PATH}:/pdb-images/protoc-gateway:/pdb-images/protoc-openapi:/pdb-images/bin"

ARG TARGETPLATFORM
RUN if [ "$TARGETPLATFORM" = "linux/amd64" ]; then ARCHITECTURE=linux-x86_64; elif [ "$TARGETPLATFORM" = "linux/arm64" ]; then ARCHITECTURE=linux-arm64; fi \
    && curl -sS -L -O "https://github.com/grpc-ecosystem/grpc-gateway/releases/download/v2.19.1/protoc-gen-grpc-gateway-v2.19.1-${ARCHITECTURE}" \
    && curl -sS -L -O "https://github.com/grpc-ecosystem/grpc-gateway/releases/download/v2.19.1/protoc-gen-openapiv2-v2.19.1-${ARCHITECTURE}" \
    && chmod +x protoc-gen-grpc-gateway-v2.19.1-${ARCHITECTURE} && mv protoc-gen-grpc-gateway-v2.19.1-${ARCHITECTURE} protoc-gateway/protoc-gen-grpc-gateway \
    && chmod +x protoc-gen-openapiv2-v2.19.1-${ARCHITECTURE} && mv protoc-gen-openapiv2-v2.19.1-${ARCHITECTURE} protoc-openapi/protoc-gen-openapiv2

# Install go 1.22.0
RUN curl https://dl.google.com/go/go1.22.0.linux-amd64.tar.gz --output /tmp/go1.22.0.linux-amd64.tar.gz \
    && tar -xzf /tmp/go1.22.0.linux-amd64.tar.gz -C /usr/local/ && rm -f /tmp/go1.22.0.linux-amd64.tar.gz

ENV GOROOT=/usr/local/go
ENV GOPATH=$HOME/go
ENV PATH=$GOPATH/bin:$GOROOT/bin:$PATH

RUN export GOBIN="/pdb-images/bin"\
    && go install google.golang.org/protobuf/cmd/protoc-gen-go@latest && go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest \
    && ./compile_protobuf.sh \
    && rm -rf protoc-gateway protoc-openapi bin

WORKDIR /pdb-images/proxy
RUN go mod init mara/mesh-service && go mod tidy

EXPOSE 46001
#EXPOSE 8081

WORKDIR /pdb-images
#ENTRYPOINT ["python3", "mesh-service-server.py"]