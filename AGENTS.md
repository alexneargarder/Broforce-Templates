# Broforce modding repos

This repo has four project templates to copy from: `Bro Template/`, `Mod Template/`, `Wardrobe Template/`, `ThunderstorePackage/`. `Scripts/` has the master copy of `BroforceModBuild.targets`, which is the MSBuild automation for building a project, installing it into the game, and optionally launching it. It also has `Makefile.common`, `sync-targets.sh`, and the Python `bt` CLI, which creates projects and packages them for Thunderstore. `README.md` covers usage and the `bt` source is under `Scripts/src/`. The `Bro Template` uses BroMakerLib.

## Build commands

From the root of a repo that uses this build system:

- `make <target>` builds one project. Targets are discovered from the project layout.
- `make build` builds all of them.
- `make build-no-launch` skips closing and launching the game.
- `make <target> LAUNCH=no` builds without the launch step.
- `make <target> INSTALL=no` skips installing to the game.
- `make <target> LAUNCH_ARGS="..."` forwards args to the launch command.
- `make clean` and `make rebuild`.
- `make cleanup-changed` runs ReSharper code cleanup on the C# files git reports as changed. It picks the project automatically when all the changes are in one, and `PROJECT=<target>` scopes it.
- `make help` lists the targets.
- From a project directory, `make -C .. <target>`.

`bt` (Python, under `Scripts/src/`) creates projects from the templates and packages Thunderstore zips with `bt package`. For the version number it takes the highest of the changelog's top header, `manifest.json` `version_number`, and `Info.json`/`.mod.json` `Version`. It warns you when the changelog is behind.

Mods are released as Thunderstore packages and installed through r2modman. Unity Mod Manager is a Thunderstore dependency of every mod package.

## Libraries and tooling

- **[RocketLib](https://github.com/Gorzontrok/RocketLib)** is the shared modding library: menus, settings, custom triggers, network helpers, loggers, UI. The entry point is `RocketLib/RocketMain.cs` and the solution is `RocketLib.sln`. It builds against UnityModManager and nothing else. Bro-Maker uses it, as do most of BroforceMods and Mods-Broforce, all of CustomBros, and BroforceOverhaulProject.
- **[Bro-Maker](https://github.com/Gorzontrok/Bro-Maker)** (BroMakerLib) is the framework for fully custom playable bros: abilities, cutscenes, unlocks, menus, loaders, vanilla presets. `BroMakerLib/Main.cs` is the entry point and `BroMakerLib.sln` is the solution. It uses RocketLib and UnityModManager. The bro mods in BroforceMods use it, as do the ones in VojkanBroforceMods and CustomBros, and the `Bro Template`.
- **[Bro-Maker wiki](https://github.com/Gorzontrok/Bro-Maker/wiki)** is documentation only. It has guides for custom bro creation: JSON and programmatic bro creation, parameter and variable references, spritesheets, cutscenes, ability-system pages (one per special, melee, passive).
- **[Unity Mod Manager fork](https://github.com/alexneargarder/unity-mod-manager)** is the loader and injector every Broforce mod loads through. `UnityModManager/ModManager.cs` is the entry point along with `Injector.cs` and `Doorstop.cs`, and the solution is `UnityModManager.sln`. It doesn't depend on anything else here. RocketLib and BroMakerLib reference `UnityModManager.dll` directly, and so do mods that use neither of them.
- **[unity-inspector-mcp](https://github.com/alexneargarder/unity-inspector-mcp)** is a Node.js MCP server for looking at and controlling the game while it runs. Tool implementations are in `index.js` and `lib/`, the client-facing side is `wrapper.js`, and there is a committed C# script library under `scripts/csharp/`. It pairs over TCP with the `Unity Inspector Mod` project in BroforceMods, which is the C# half and gets built and installed separately.
- **[r2modmanPlus fork](https://github.com/alexneargarder/r2modmanPlus)** is the Thunderstore mod manager desktop app, Electron with Quasar/Vue. Upstream is [ebkr/r2modmanPlus](https://github.com/ebkr/r2modmanPlus). It installs mods and holds the local Broforce profiles that builds install into. The entry points are `src-electron/electron-main.ts` and `src/`, build config is `quasar.config.ts`, and dev setup is covered by `DevEnvSetup.md` and `BUILDING.md`. It uses a Node and Yarn toolchain and is unrelated to the C# build graph.

## Mod collections

- **[BroforceMods](https://github.com/alexneargarder/BroforceMods)** has Captain Ameribro, Furibrosa, Mission Impossibro, RJBrocready, Drunken Broster, Brostbuster, Swap Bros Mod, Utility Mod, Unity Inspector Mod, IronBro Multiplayer Mod, Randomizer Mod, Control Enemies Mod, BroforceDevTools, ExampleMod. Each mod is laid out as `<Name>/<Name>/Main.cs`, packaged output and the changelog go under `Releases/<Name>/`, and the DLLs to compile against are in `libs/`. Most of them use RocketLib and many also use BroMakerLib.
- **[BroforceMods wiki](https://github.com/alexneargarder/BroforceMods/wiki)** covers general modding: creating a UMM mod, patching with Harmony, dev environment setup, finding the mods folder, using the `bt` script, viewing the game's code.
- **[Mods-Broforce](https://github.com/Gorzon38/Mods-Broforce)** has 26 mod projects: 007_Patch, ActivateModsOnline, AutoEnterPassword, BroforceOverhaul, CustomHeroName, DresserMod, ExpendablesBrosInGame, FilteredBros, ForBralef, LevelEditorExtended, MapDataController, NoMoreCutscenes, OnlyPockettedSpecialAmmo, Pigstini, Proc_Gen_Mod, RogueforceMod, SatanSurprise, SearchLocalCampaignFaster, ShowAvatarFaceHugger, SkeletonDeadFace, SkipIntro, SmallerHUD, Spooktober, TankBroRocketForBrominator, TrophyManager, TweaksFromPigs. The layout varies. A few are flat `<Mod>/<Mod>.csproj` and most are under `src/`. The top-level `RocketLib/` folder is left from when RocketLib was developed in this repo. It keeps the old release zips, and the source has moved to its own repo. The `Makefile` is hand-written, and `make build` only covers the five projects that import `BroforceModBuild.targets`: SkipIntro, ExpendablesBrosInGame, FilteredBros, 007_Patch, DresserMod. The other 21 keep hardcoded references, with no install or launch automation. Nearly all of them use RocketLib and none use BroMakerLib.
- **[CustomBros](https://github.com/Gorzontrok/CustomBros)** has Bronobi, SantaBraus, TonyBrotana, each in its own project directory, with `Release/` and `Repository.json` at the repo root. Bronobi uses RocketLib and BroMakerLib, the other two only RocketLib.
- **[VojkanBroforceMods](https://github.com/VojkanSE87/BroforceMods)** has Cobro and Jack Broton as C# projects at `Cobro/Cobro/Cobro.csproj` and `Jack Broton/Jack Broton/Jack Broton.csproj`, plus BroMaxForeheadFix and CorrectRambro, which are sprite-only and consist of a `.fa.json` and a PNG with no code. Packaged output goes under `Releases/<Mod>/`. The two code mods reference BroMakerLib and get RocketLib transitively.
- **[BroforceOverhaulProject](https://github.com/Gorzontrok/BroforceOverhaulProject)** has TerroristC4Programs, TheGeneralsTraining, four projects under `BrosTrainedByTheGeneral/` (BroCeasarTrained, BrommandoTrained, BroffyTrained, LeeBroxmasTrained), and the asset-only VillagerSecretTraining. The root `Repository.json` is the closest thing to an index. Most of them use RocketLib through hardcoded Windows paths and none use BroMakerLib.

## Dependency direction

Unity Mod Manager is at the bottom. RocketLib builds on top of it, BroMakerLib builds on RocketLib, and the mods build on those.

Broforce-Templates supplies the build system (`BroforceModBuild.targets` and `Makefile.common`) to BroforceMods, Bro-Maker, RocketLib, Mods-Broforce, VojkanBroforceMods. CustomBros has `BroforceModBuild.targets` and no `Makefile.common`, so there's no `make` wrapper there.

`sync-targets.sh` copies the build files out to the consumer repos in its list, and it only writes files a consumer already has. It takes `--dry-run`, `--check`, `--repo` to scope it to one repo, and `--repo-path NAME=PATH` for a consumer at another checkout.

## Reference

The decompiled game code is not public. To read the base-game classes you decompile the game's `Assembly-CSharp.dll` yourself with dnSpy or ILSpy. Mods compile against the `Assembly-CSharp.dll` vendored in each repo's `libs/`, not against that decompiled source.

[Broforce-Docs](https://github.com/alexneargarder/Broforce-Docs) holds XML API documentation for the game classes, one file per class under `Classes/`, aggregated into `Assembly-CSharp.xml` so dnSpy and Visual Studio can show tooltips. Edit the files in `Classes/` and regenerate with `Scripts/build-documentation.py`. Don't edit the aggregate by hand. `README.md` there describes the workflow.
