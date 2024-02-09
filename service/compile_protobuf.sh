#python -m grpc_tools.protoc -I . --python_out=. --grpc_python_out=. --grpc-gateway_out . meshservice.proto
python3 -m grpc_tools.protoc -I . --python_out=. --grpc_python_out=. meshservice.proto