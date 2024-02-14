import grpc
import os
import tempfile
from meshservice_pb2 import MeshRequestDefault, MeshChunk, RequestArguments, RepresentationMode
from meshservice_pb2_grpc import MeshServiceStub

class MeshServiceClient():
    def __init__(self, address: str):
        options = [('grpc.max_send_message_length', 512 * 1024 * 1024),
                   ('grpc.max_receive_message_length', 512 * 1024 * 1024)]
        self.channel = grpc.insecure_channel(address, options=options)
        self.client = MeshServiceStub(self.channel)
        self.temporary_directories = []

    def write_to_file(self, out_path: str, payload):
        with open(out_path, "wb") as output:
            output.write(payload)

    def GetMesh(self, pdbId: str, representationMode: str = "mesh", showHydrogens=False, showBranchedSticks=False,
                ensembleShades=False, forceBfactor=False):

        # repMode = RepresentationMode.keys().index(representationMode.upper())
        # arguments = RequestArguments(repMode=repMode, showHydrogens=showHydrogens,
        #                              showBranchedSticks=showBranchedSticks, ensembleShades=ensembleShades,
        #                              forceBfactor=forceBfactor)

        chunks = self.client.GetMesh(MeshRequestDefault(pdbId=pdbId))
        output_files = []
        temp_dir = tempfile.mkdtemp(prefix="usdz-meshes")
        self.temporary_directories.append(temp_dir)
        current_file = ""
        received_bytes = bytes()
        for c in chunks:
            if c.name != current_file:
                current_file = c.name
                self.write_to_file(os.path.join(temp_dir, current_file), received_bytes)
                received_bytes = bytes()
                output_files.append(temp_dir + current_file)
            received_bytes += c.chunk
        if len(received_bytes):
            self.write_to_file(os.path.join(temp_dir, current_file), received_bytes)
        
        return output_files

    def Clean(self):
        for d in self.temporary_directories:
            os.rmdir(d)


client = MeshServiceClient("localhost:46001")
mesh_paths = client.GetMesh("1x8x")

print(mesh_paths)
