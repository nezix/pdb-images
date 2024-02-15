import grpc
import os
import subprocess
import tempfile
from concurrent import futures
from meshservice_pb2 import MeshChunk, RequestArguments, RepresentationMode
import meshservice_pb2_grpc
class MeshService(meshservice_pb2_grpc.MeshServiceServicer):
    def file_to_bytes(self, path):
        with open(path, "rb") as image:
            f = image.read()
            return f
    def run_pdb_images_pdbid(self, pdbId: str, output_folder: str, arguments: RequestArguments = None):
        if arguments is None:
            arguments = RequestArguments(repMode=RepresentationMode.MESH, showHydrogens=False, showBranchedSticks=True,
                                         ensembleShades=False, forceBfactor=False)
        args = ["xvfb-run", "--auto-servernum", "pdb-images", pdbId, output_folder, "--type",
                self.ToPdbImagesArg(arguments.repMode)]
        if arguments.showHydrogens:
            args += ["--show-hydrogens"]
        if arguments.showBranchedSticks:
            args += ["--show-branched-sticks"]
        if arguments.ensembleShades:
            args += ["--ensemble-shades"]
        if arguments.forceBfactor:
            args += ["--force-bfactor"]

        print(f"Starting with args: {args}")

        result = subprocess.run(args, capture_output=True)
        if len(result.stderr) > 0:
            return result.stderr.decode("utf-8")
        return ""

    def ToPdbImagesArg(self, mode: int):
        return RepresentationMode.keys()[mode].lower()

    def _chunk_bytes(self, name: str, data, chunker_size=1024*1024):
        index = 0
        while index < len(data):
            yield MeshChunk(name=name, chunk=data[index:index + chunker_size])
            index += chunker_size

    def GetMesh(self, request, context):
        # context.set_compression(grpc.Compression.Gzip)
        print("Run pdb-images for " + request.pdbId)
        tempdir_out = tempfile.TemporaryDirectory(prefix="pdb_images_output_")
        ret = self.run_pdb_images_pdbid(request.pdbId.lower(), tempdir_out.name)
        if ret:
            raise Exception(f"Something went wrong when executing pdb-images: {ret}")

        for m_path in os.listdir(tempdir_out.name):
            if not m_path.endswith(".usdz"):
                continue
            usdzData = self.file_to_bytes(os.path.join(tempdir_out.name, m_path))
            return self._chunk_bytes(m_path, usdzData)

        # tempdir_out.cleanup()


def serve(port):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    meshservice_pb2_grpc.add_MeshServiceServicer_to_server(MeshService(), server)
    server.add_insecure_port(f"[::]:{port}")
    print(f"Server running on {port}")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve(46001)
