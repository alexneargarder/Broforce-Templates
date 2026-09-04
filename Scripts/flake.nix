{
  description = "Broforce modding tools for creating mods and packaging for Thunderstore";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
      btVersion = (builtins.fromTOML (builtins.readFile ./pyproject.toml)).project.version;
    in
    {
      packages = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          python3 = pkgs.python3;
        in
        {
          default = python3.pkgs.buildPythonApplication {
            pname = "broforce-tools";
            version = btVersion;

            # pyproject.toml lives in Scripts/, but setup.py's build_py bundles the
            # templates from the repo root, so the whole repo is the source.
            src = ./..;
            setSourceRoot = "sourceRoot=$(echo */Scripts)";

            pyproject = true;

            build-system = [ python3.pkgs.setuptools ];

            dependencies = with python3.pkgs; [
              typer
              questionary
              rich
              shellingham
            ];

            pythonImportsCheck = [ "broforce_tools" ];

            makeWrapperArgs = [ "--set BROFORCE_TEMPLATES_DIR ${placeholder "out"}/${python3.sitePackages}/broforce_tools/templates" ];

            postInstall = ''
              # Install bash completion
              mkdir -p $out/share/bash-completion/completions
              cp completions/broforce-tools $out/share/bash-completion/completions/broforce-tools
              ln -s broforce-tools $out/share/bash-completion/completions/bt
            '';

            meta = with pkgs.lib; {
              description = "Tool for creating Broforce mods and packaging for Thunderstore";
              homepage = "https://github.com/alexneargarder/Broforce-Templates";
              license = licenses.mit;
              platforms = platforms.linux;
              mainProgram = "bt";
              maintainers = [ ];
            };
          };
        });

      devShells = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          pythonWithDevDeps = pkgs.python3.withPackages (ps: with ps; [
            typer
            questionary
            rich
            shellingham
            pytest
          ]);
        in
        {
          default = pkgs.mkShell {
            packages = [ pythonWithDevDeps pkgs.bash-completion ];
            shellHook = ''
              # Find the live working tree. BROFORCE_SCRIPTS_DIR wins, else $PWD if
              # it looks like the Scripts dir, else give up and stay in store mode.
              if [ -n "''${BROFORCE_SCRIPTS_DIR:-}" ] && [ -d "$BROFORCE_SCRIPTS_DIR/src/broforce_tools" ]; then
                SRC_DIR="$BROFORCE_SCRIPTS_DIR"
              elif [ -d "$PWD/src/broforce_tools" ]; then
                SRC_DIR="$PWD"
              else
                echo "warning: no live source found; set BROFORCE_SCRIPTS_DIR or cd to Scripts/"
                SRC_DIR=""
              fi
              if [ -n "$SRC_DIR" ]; then
                export PYTHONPATH="$SRC_DIR/src:$PYTHONPATH"
                BT_DEV_BIN="$(mktemp -d -t bt-dev.XXXXXX)"
                cat > "$BT_DEV_BIN/bt" <<EOF
#!${pkgs.bash}/bin/bash
exec ${pythonWithDevDeps}/bin/python -m broforce_tools "\$@"
EOF
                chmod +x "$BT_DEV_BIN/bt"
                cp "$BT_DEV_BIN/bt" "$BT_DEV_BIN/broforce-tools"
                export PATH="$BT_DEV_BIN:$PATH"
                trap "rm -rf '$BT_DEV_BIN'" EXIT

                # Load bash-completion and the live completion script so tab-complete
                # picks up newly-added flags/commands without a rebuild.
                if [ -n "''${BASH_VERSION:-}" ]; then
                  if [ -z "''${BASH_COMPLETION_VERSINFO:-}" ] && [ -f ${pkgs.bash-completion}/share/bash-completion/bash_completion ]; then
                    source ${pkgs.bash-completion}/share/bash-completion/bash_completion
                  fi
                  if [ -f "$SRC_DIR/completions/broforce-tools" ]; then
                    source "$SRC_DIR/completions/broforce-tools"
                  fi
                fi

                echo "bt (dev) → $SRC_DIR/src/broforce_tools"
              fi
            '';
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
              description = ''
                Parent directory containing Broforce mod repositories.

                Note: the activation script always writes its generated config to
                `~/.config/broforce-tools/config.nix.json`, ignoring any per-user
                `XDG_CONFIG_HOME` override.
              '';
            };

            releaseDir = mkOption {
              type = types.nullOr types.str;
              default = null;
              example = "~/repos/Releases";
              description = "Central directory to copy release zips into after packaging.";
            };

            repos = mkOption {
              type = types.listOf types.str;
              default = [ ];
              example = [ "BroforceMods" "RocketLib" ];
              description = "List of repository names to search for projects.";
            };

            ignore = mkOption {
              type = types.attrsOf (types.listOf types.str);
              default = { };
              example = { BroforceMods = [ "ExampleMod" ]; };
              description = "Map of repo names to lists of project names to skip.";
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

            developer = {
              enable = mkEnableOption "bt-dev wrapper that runs the live source tree";

              scriptsDir = mkOption {
                type = types.str;
                example = "/home/you/repos/Broforce-Templates/Scripts";
                description = ''
                  Absolute path to the Broforce-Templates/Scripts checkout.
                  `bt-dev` will enter `nix develop` on this directory so `bt`
                  runs the live source (no rebuild between edits).
                '';
              };
            };
          };

          config = mkIf cfg.enable {
            environment.systemPackages = [ cfg.package ]
              ++ lib.optional cfg.developer.enable (pkgs.writeShellScriptBin "bt-dev" ''
                # Enter a dev shell where `bt` runs the live broforce-tools source.
                # Edits to src/broforce_tools/*.py take effect on the next `bt` invocation.
                #
                # Usage:
                #   bt-dev              # interactive shell with `bt` mapped to dev version
                #   bt-dev <args>       # run a single `bt` command then exit
                set -euo pipefail
                export BROFORCE_SCRIPTS_DIR=${lib.escapeShellArg cfg.developer.scriptsDir}
                if [ "$#" -eq 0 ]; then
                  exec ${pkgs.nix}/bin/nix develop "$BROFORCE_SCRIPTS_DIR"
                else
                  exec ${pkgs.nix}/bin/nix develop "$BROFORCE_SCRIPTS_DIR" --command bt "$@"
                fi
              '');

            system.activationScripts.broforce-tools = let
              configJson = builtins.toJSON ({
                repos = cfg.repos;
              } // optionalAttrs (cfg.reposParent != null) {
                repos_parent = cfg.reposParent;
              } // optionalAttrs (cfg.releaseDir != null) {
                release_dir = cfg.releaseDir;
              } // optionalAttrs (cfg.ignore != {}) {
                inherit (cfg) ignore;
              } // optionalAttrs (cfg.defaults.namespace != null || cfg.defaults.websiteUrl != null) {
                defaults = filterAttrs (n: v: v != null) {
                  namespace = cfg.defaults.namespace;
                  website_url = cfg.defaults.websiteUrl;
                };
              });
            in mkIf (cfg.repos != [] || cfg.reposParent != null || cfg.releaseDir != null
                     || cfg.ignore != {} || cfg.defaults.namespace != null
                     || cfg.defaults.websiteUrl != null) ''
              for user_home in /home/*; do
                # Skip users without an existing ~/.config so we never create it as root.
                if [ -d "$user_home/.config" ]; then
                  home_owner=$(stat -c %u:%g "$user_home")
                  config_dir="$user_home/.config/broforce-tools"

                  mkdir -p "$config_dir"
                  echo '${configJson}' > "$config_dir/config.nix.json"
                  chown "$home_owner" "$config_dir" "$config_dir/config.nix.json"
                fi
              done
            '';
          };
        };
    };
}
