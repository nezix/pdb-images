python3 -m grpc_tools.protoc -I . --python_out=. --grpc_python_out=. meshservice.proto google/api/*.proto protoc-gen-openapiv2/options/*.proto

python3 -m grpc_tools.protoc -I . --go_out=./proxy/gateway --go_opt paths=source_relative \
--go-grpc_out=./proxy/gateway --go-grpc_opt paths=source_relative \
--grpc-gateway_out=./proxy/gateway --grpc-gateway_opt paths=source_relative \
--openapiv2_out=logtostderr=true:./openapi/ meshservice.proto google/api/*.proto protoc-gen-openapiv2/options/*.proto
