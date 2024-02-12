FROM ubuntu:22.04

RUN apt-get update -y
RUN apt-get install -y curl xvfb golang-go protobuf-compiler
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

#COPY docker ./docker

#ENTRYPOINT ["bash", "/pdb-images/docker/entrypoint.sh"]

RUN apt install -y python3-pip
RUN pip3 install grpcio-tools

RUN mkdir -p /pdb-images/out

COPY ["service/compile_protobuf.sh", "service/meshservice/meshservice.proto", "service/meshservice/mesh-service-server.py", "./"]
COPY ["service/google/", "./google/"]
COPY ["service/protoc-gen-openapiv2/", "./protoc-gen-openapiv2/"]

RUN mkdir -p /pdb-images/protoc-gateway /pdb-images/protoc-openapi /pdb-images/proxy /pdb-images/openapi /pdb-images/bin
ENV PATH="${PATH}:/pdb-images/protoc-gateway:/pdb-images/protoc-openapi:/pdb-images/bin"

ARG TARGETPLATFORM
RUN if [ "$TARGETPLATFORM" = "linux/amd64" ]; then ARCHITECTURE=linux-x86_64; elif [ "$TARGETPLATFORM" = "linux/arm64" ]; then ARCHITECTURE=linux-arm64; fi \
    && curl -sS -L -O "https://github.com/grpc-ecosystem/grpc-gateway/releases/download/v2.19.1/protoc-gen-grpc-gateway-v2.19.1-${ARCHITECTURE}" \
    && curl -sS -L -O "https://github.com/grpc-ecosystem/grpc-gateway/releases/download/v2.19.1/protoc-gen-openapiv2-v2.19.1-${ARCHITECTURE}" \
    && chmod +x protoc-gen-grpc-gateway-v2.19.1-${ARCHITECTURE} && mv protoc-gen-grpc-gateway-v2.19.1-${ARCHITECTURE} protoc-gateway/protoc-gen-grpc-gateway \
    && chmod +x protoc-gen-openapiv2-v2.19.1-${ARCHITECTURE} && mv protoc-gen-openapiv2-v2.19.1-${ARCHITECTURE} protoc-openapi/protoc-gen-openapiv2

RUN export GOBIN="/pdb-images/bin"\
    && go install google.golang.org/protobuf/cmd/protoc-gen-go@latest && go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest \
    && ./compile_protobuf.sh \ 
    && rm -rf protoc-gateway protoc-openapi bin

EXPOSE 46001

ENTRYPOINT ["python3", "mesh-service-server.py"]