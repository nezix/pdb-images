import grpc
import os
import subprocess
import tempfile
from concurrent import futures
from meshservice_pb2 import MeshResult, Mesh, RequestArguments, RepresentationMode
import meshservice_pb2_grpc

class MeshService(meshservice_pb2_grpc.MeshServiceServicer):
    def file_to_bytes(self, path):
        with open(path, "rb") as image:
            f = image.read()
            return f
    def run_pdb_images_pdbid(self, pdbId: str, output_folder: str, arguments: RequestArguments):
        print(arguments.repMode, self.ToPdbImagesArg(arguments.repMode))
        args = ["xvfb-run", "--auto-servernum", "pdb-images",pdbId, output_folder, "--type", self.ToPdbImagesArg(arguments.repMode)]
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
    
    def extract_repmode_from_path(self, path: str):
        # TODO
        return RepresentationMode.ALL
    def GetMesh(self, request, context):
        arguments = request.arguments
        print("Run pdb-images for "+request.pdbId)
        tempdir_out = tempfile.TemporaryDirectory(prefix="pdb_images_output_")
        ret = self.run_pdb_images_pdbid(request.pdbId, tempdir_out.name, arguments)
        if ret:
            raise Exception(f"Something went wrong when executing pdb-images: {ret}")
        
        rendered_meshes = []
        for m_path in os.listdir(tempdir_out.name):
            if not m_path.endswith(".usdz"):
                continue
            repMode = self.extract_repmode_from_path(m_path)
            bytes = self.file_to_bytes(os.path.join(tempdir_out.name, m_path))
            rendered_meshes.append(Mesh(name=m_path, usdzData=bytes, repMode=repMode))

        tempdir_out.cleanup()
        return MeshResult(meshes=rendered_meshes)

def serve(port):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    meshservice_pb2_grpc.add_MeshServiceServicer_to_server(MeshService(), server)
    server.add_insecure_port(f"[::]:{port}")
    print(f"Server running on {port}")
    server.start()
    server.wait_for_termination()

if __name__ == "__main__":
    serve(46001)