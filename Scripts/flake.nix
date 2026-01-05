{
  description = "Broforce modding tools for creating mods and packaging for Thunderstore";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
    in
    {
      packages = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};

          pythonWithDeps = pkgs.python3.withPackages (ps: with ps; [
            typer
            questionary
            rich
            shellingham
          ]);
        in
        {
          default = pkgs.stdenv.mkDerivation {
            pname = "broforce-tools";
            version = "1.0.0";

            src = ./..;

            nativeBuildInputs = [ pkgs.makeWrapper ];

            buildInputs = [ pythonWithDeps ];

            installPhase = ''
              runHook preInstall

              # Create directories
              mkdir -p $out/bin
              mkdir -p $out/lib/python3/site-packages
              mkdir -p $out/share/broforce-tools

              # Copy Python package
              cp -r Scripts/src/broforce_tools $out/lib/python3/site-packages/

              # Copy templates to share directory
              cp -r "Bro Template" $out/share/broforce-tools/
              cp -r "Mod Template" $out/share/broforce-tools/
              cp -r "ThunderstorePackage" $out/share/broforce-tools/

              # Copy BroforceModBuild.targets
              mkdir -p $out/share/broforce-tools/Scripts
              cp Scripts/BroforceModBuild.targets $out/share/broforce-tools/Scripts/

              # Create wrapper script
              cat > $out/bin/broforce-tools << 'WRAPPER'
#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib', 'python3', 'site-packages'))
from broforce_tools import main
main()
WRAPPER
              chmod +x $out/bin/broforce-tools

              # Create bt alias
              ln -s $out/bin/broforce-tools $out/bin/bt

              # Patch shebangs
              patchShebangs $out/bin/broforce-tools

              # Wrap script with environment
              wrapProgram $out/bin/broforce-tools \
                --set BROFORCE_TEMPLATES_DIR "$out/share/broforce-tools" \
                --prefix PATH : ${pkgs.lib.makeBinPath [ pythonWithDeps ]}

              # Install bash completion
              mkdir -p $out/share/bash-completion/completions
              cp Scripts/completions/broforce-tools $out/share/bash-completion/completions/broforce-tools

              # Patch completion script for Nix
              substituteInPlace $out/share/bash-completion/completions/broforce-tools \
                --replace-fail 'python3 -m broforce_tools' \
                "PYTHONPATH=\"$out/lib/python3/site-packages\" ${pythonWithDeps}/bin/python3 -m broforce_tools"

              runHook postInstall
            '';

            meta = with pkgs.lib; {
              description = "Tool for creating Broforce mods and packaging for Thunderstore";
              homepage = "https://github.com/alexneargarder/Broforce-Templates";
              license = licenses.mit;
              platforms = platforms.linux;
              maintainers = [ ];
            };
          };
        });

      nixosModules.default = { config, lib, pkgs, ... }:
        with lib;
        let
          cfg = config.programs.broforce-tools;
        in
        {
          options.programs.broforce-tools = {
            enable = mkEnableOption "broforce-tools";

            package = mkOption {
              type = types.package;
              default = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
              defaultText = literalExpression "self.packages.\${pkgs.stdenv.hostPlatform.system}.default";
              description = "The broforce-tools package to use.";
            };

            reposParent = mkOption {
              type = types.nullOr types.str;
              default = null;
              example = "~/repos";
              description = "Parent directory containing Broforce mod repositories.";
            };

            repos = mkOption {
              type = types.listOf types.str;
              default = [ ];
              example = [ "BroforceMods" "RocketLib" ];
              description = "List of repository names to search for projects.";
            };

            defaults = {
              namespace = mkOption {
                type = types.nullOr types.str;
                default = null;
                example = "AlexNeargarder";
                description = "Default namespace/author for Thunderstore packages.";
              };

              websiteUrl = mkOption {
                type = types.nullOr types.str;
                default = null;
                example = "https://github.com/alexneargarder/BroforceMods";
                description = "Default website URL for Thunderstore packages.";
              };
            };
          };

          config = mkIf cfg.enable {
            environment.systemPackages = [ cfg.package ];

            system.activationScripts.broforce-tools = let
              configJson = builtins.toJSON ({
                repos = cfg.repos;
              } // optionalAttrs (cfg.reposParent != null) {
                repos_parent = cfg.reposParent;
              } // optionalAttrs (cfg.defaults.namespace != null || cfg.defaults.websiteUrl != null) {
                defaults = filterAttrs (n: v: v != null) {
                  namespace = cfg.defaults.namespace;
                  website_url = cfg.defaults.websiteUrl;
                };
              });
            in mkIf (cfg.repos != [] || cfg.reposParent != null || cfg.defaults.namespace != null) ''
              for user_home in /home/*; do
                if [ -d "$user_home" ]; then
                  user_name=$(basename "$user_home")
                  config_dir="$user_home/.config/broforce-tools"

                  mkdir -p "$config_dir"
                  chown "$user_name:users" "$config_dir"

                  echo '${configJson}' > "$config_dir/config.json"
                  chown "$user_name:users" "$config_dir/config.json"
                fi
              done
            '';
          };
        };
    };
}
