with import <nixpkgs> { };
pkgs.mkShell {
  name = "dmp-project";

  NIX_LD_LIBRARY_PATH = lib.makeLibraryPath [
    stdenv.cc.cc # libstdc++
    zlib # libz (for numpy)
  ];

  NIX_LD = lib.fileContents "${stdenv.cc}/nix-support/dynamic-linker";

  # --- SSL Certificate Fixes ---
  SSL_CERT_FILE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
  GIT_SSL_CAINFO = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
  REQUESTS_CA_BUNDLE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";

  packages = with pkgs; [
    uv
    cmake
    gcc
    gnumake
  ];

  shellHook = ''
    export LD_LIBRARY_PATH=$NIX_LD_LIBRARY_PATH
  '';
}
