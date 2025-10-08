import reflex as rx
from reflex.utils.compat import sqlmodel
import os, subprocess
import pathlib
from typing import List

from .database import Game, GameStatus
from redis.asyncio import Redis

# db = GameDatabase(redis=Redis(host="192.168.0.14"))


class Config(rx.State):
    container_name: str = "my_container"
    image: str = "farrar142/mvix"

    @rx.event
    def set_container_name(self, name: str):
        self.container_name = name or "my_container"

    @rx.event
    def set_image(self, image: str):
        self.image = image


class Games(rx.State):
    games: list[Game] = []

    @rx.event(background=True)
    async def on_load(self):
        with rx.session() as session:
            async with self:
                self.games = [*session.exec(Game.select()).all()]
                for game in self.games:
                    if not game.id:
                        continue
                    await self.set_game_status(session, game.id)

    @rx.event(background=True)
    async def load_games(self):
        with rx.session() as session:
            async with self:
                self.games = [*session.exec(Game.select()).all()]

    @rx.event(background=True)
    async def add_game(self, dir: str):
        # dir하위에 www폴더가 있는지 확인
        if not os.path.exists(os.path.join(dir, "index.html")):
            # DirectoryState의 에러 메세지로 변경
            async with self:
                directory = await self.get_state(DirectoryState)
                directory.error_message = f"'index.html' 파일이{dir}에 없습니다."
                return

        with rx.session() as session:
            port = 3000
            if last_game := session.exec(
                Game.select().order_by(Game.port.desc())
            ).first():
                port = last_game.port + 1
            async with self:
                config = await self.get_state(Config)
                game = Game(
                    dir=dir,
                    port=port,
                    container_name=config.container_name,
                    image=config.image,
                )
                session.add(game)
                session.commit()
                self.games.append(game)

    @rx.event(background=True)
    async def delete_game(self, id: int):
        with rx.session() as session:
            game = session.get(Game, id)
            if game:
                session.delete(game)
                session.commit()
                async with self:
                    self.games = [g for g in self.games if g.id != id]

    async def set_game_status(self, session: sqlmodel.Session, id: int) -> bool:
        game = session.get(Game, id)
        if not game:
            return False
        "도커 컨테이너의 실행 상태를 반환합니다, 컨테이너가 없으면 False, 실행중이지 않으면 False, 실행중이면 True"
        docker_ps = subprocess.run(
            [
                "docker",
                "ps",
                "--filter",
                f"name={game.container_name}",
                "--format",
                "{{.Names}}",
            ],
            capture_output=True,
            text=True,
        )
        if docker_ps.returncode != 0:
            game.status = GameStatus.STOPPED
        elif game.container_name in docker_ps.stdout.splitlines():
            game.status = GameStatus.RUNNING
        else:
            game.status = GameStatus.STOPPED
        session.add(game)
        session.commit()
        return True

    @rx.event(background=True)
    async def run_game(self, id: int):
        with rx.session() as session:
            print("run game")
            game = next((g for g in self.games if g.id == id), None)
            if not game:
                print("게임을 찾을 수 없습니다.")
                return

            print(
                f"Running game with ID: {id} and port: {game.port} and status {game.status}"
            )

            async def inner():
                docker_run = f"docker run -it --init -v {game.dir}:/game -p {game.port}:3000 --name {game.container_name} -e DEBUG=true -d {game.image}"
                process = subprocess.run(
                    docker_run.split(), capture_output=True, text=True
                )
                print(process)
                if process.returncode == 0:

                    async with self:
                        game.status = GameStatus.RUNNING
                        session.add(game)
                        session.commit()
                else:
                    port_errors = [
                        "ports are not available",
                        "port is already allocated",
                        "already in use",
                    ]
                    if any(err in process.stderr for err in port_errors):

                        docker_stop = f"docker rm -f {game.container_name}"
                        process = subprocess.run(
                            docker_stop.split(), capture_output=True, text=True
                        )
                        async with self:
                            game.port += 1
                            session.add(game)
                            session.commit()
                        await inner()
                    container_name_errors = ["Conflict. The container name"]
                    if any(err in process.stderr for err in container_name_errors):
                        docker_stop = f"docker rm -f {game.container_name}"
                        process = subprocess.run(
                            docker_stop.split(), capture_output=True, text=True
                        )
                        await inner()

            await inner()

    @rx.event(background=True)
    async def stop_game(self, id: int):
        with rx.session() as session:
            print("stop game")
            game = next((g for g in self.games if g.id == id), None)
            if not game:
                print("게임을 찾을 수 없습니다.")
                return
            async with self:

                print(
                    f"Stopping game with ID: {id} and port: {game.port} and status {game.status}"
                )
                docker_stop = f"docker rm -f {game.container_name}"
                process = subprocess.run(
                    docker_stop.split(), capture_output=True, text=True
                )
                if process.returncode == 0:
                    game.status = GameStatus.STOPPED
                    session.add(game)
                    session.commit()
                else:
                    print("도커 컨테이너를 중지할 수 없습니다.")

    @rx.event
    def move_to_url(self, port: int):
        # 주소창의 호스트 가져오기 127.0.0.1:3000으로 들어가면 127.0.0.1이 나오도록, 192.168.0.14:3000으로 들어가면 192.168.0.14가 나오도록
        # callscript가 작동 안해
        print("call")
        return rx.call_script(
            "window.open(location.protocol + '//' + location.hostname + ':"
            + str(port)
            + "', '_blank')"
        )

    @rx.event
    def move_to_url_callback(self, host):
        splitted = host.split(":")[0]
        return rx.call_script(
            f"window.open('http://{splitted}:{host.split(':')[1]}', '_blank')"
        )
        print(host)


class DirectoryState(rx.State):
    """디렉토리 탐색 상태 관리"""

    current_path: str = os.getcwd()
    directories: List[str] = []
    files: List[str] = []
    error_message: str = ""
    selected_directory: str = ""

    @rx.event
    async def refresh(self):
        """디렉토리 내용 새로고침"""
        print("Refreshing directory:", self.current_path)
        try:
            self.error_message = ""
            path = pathlib.Path(self.current_path)

            dirs = []
            files = []

            # 상위 디렉토리 추가 (루트가 아닌 경우)
            if path.parent != path:
                dirs.append("..")

            # 현재 디렉토리의 내용들 가져오기
            try:
                for item in sorted(path.iterdir()):
                    if item.is_dir():
                        dirs.append(item.name)
                    else:
                        files.append(item.name)

                self.directories = dirs
                self.files = files
                config = await self.get_state(Config)
                if self.current_path.endswith("www"):
                    config.set_container_name(self.current_path.split(os.sep)[-2])
                else:
                    config.set_container_name(self.current_path.split(os.sep)[-1])

            except PermissionError:
                self.error_message = f"권한이 없습니다: {self.current_path}"
                self.directories = []
                self.files = []
            except Exception as e:
                self.error_message = f"오류 발생: {str(e)}"
                self.directories = []
                self.files = []

        except Exception as e:
            self.error_message = f"디렉토리를 읽을 수 없습니다: {str(e)}"
            self.directories = []
            self.files = []

    @rx.event
    async def go_to_parent(self):
        """상위 디렉토리로 이동"""
        try:
            print("Going to parent directory")
            new_path = pathlib.Path(self.current_path).parent
            print(new_path)
            if new_path.exists() and new_path.is_dir():
                print("Going to parent directory:", new_path)
                self.current_path = str(new_path.resolve())
                print("await refresh")
                await self.refresh()
        except Exception as e:
            self.error_message = f"상위 디렉토리로 이동 중 오류: {str(e)}"
            raise e

    @rx.event
    async def change_directory(self, directory_name: str):
        """지정된 디렉토리로 이동"""
        try:
            if directory_name == "..":
                await self.go_to_parent()
                return

            new_path = pathlib.Path(self.current_path) / directory_name
            if new_path.exists() and new_path.is_dir():
                self.current_path = str(new_path.resolve())
                await self.refresh()
            else:
                self.error_message = f"디렉토리를 찾을 수 없습니다: {directory_name}"
        except PermissionError:
            self.error_message = f"권한이 없습니다: {directory_name}"
        except Exception as e:
            self.error_message = f"디렉토리 이동 중 오류: {str(e)}"

    @rx.event
    async def set_selected_directory(self, directory_name: str):
        """선택된 디렉토리 설정 후 이동"""
        self.selected_directory = directory_name
        await self.change_directory(directory_name)


def index() -> rx.Component:
    """메인 페이지"""
    return rx.container(
        rx.vstack(
            # 헤더
            rx.heading(
                "RPGMaker Docker Hosting",
                size="9",
                margin_bottom="2rem",
                text_align="center",
            ),
            rx.divider(margin_bottom="2rem"),
            # 컨트롤 버튼들
            rx.hstack(
                rx.button(
                    "🔄 새로고침", on_click=DirectoryState.refresh, color_scheme="blue"
                ),
                rx.button(
                    "⬆️ 상위 폴더",
                    on_click=DirectoryState.go_to_parent,
                    color_scheme="green",
                ),
                rx.button(
                    "🎮 게임 로드", on_click=Games.load_games, color_scheme="teal"
                ),
                rx.button(
                    "🆕 게임 추가",
                    on_click=lambda: Games.add_game(DirectoryState.current_path),
                    color_scheme="orange",
                ),
                spacing="4",
                margin_bottom="2rem",
            ),
            # 오류 메시지 표시
            rx.cond(
                DirectoryState.error_message != "",
                rx.box(
                    rx.hstack(
                        rx.text("⚠️ 오류: ", color="red", weight="bold"),
                        rx.text(DirectoryState.error_message, color="red"),
                        align="center",
                    ),
                    padding="15px",
                    background_color="red.50",
                    border="1px solid red",
                    border_radius="md",
                    margin_bottom="2rem",
                    width="100%",
                ),
            ),
            # 메인 컨테이너
            rx.hstack(
                # 게임 목록
                rx.vstack(
                    rx.vstack(
                        rx.heading("🎮 설정", size="6", margin_bottom="1rem"),
                        rx.vstack(
                            rx.hstack(
                                rx.text("이미지"),
                                # 도커 이미지 설정
                                rx.select(
                                    items=[
                                        "farrar142/mvix",
                                        "ghcr.io/flandredaisuki/mvix",
                                    ],
                                    default_value=Config.image,
                                    on_change=Config.set_image,
                                ),
                                align="center",
                            ),
                            rx.text_field(
                                placeholder="컨테이너 이름",
                                value=Config.container_name,
                                on_change=Config.set_container_name,
                            ),
                        ),
                    ),
                    rx.box(
                        rx.heading("🎮 저장된 게임", size="5", margin_bottom="1rem"),
                        rx.vstack(
                            rx.foreach(
                                Games.games,
                                lambda game: rx.box(
                                    rx.hstack(
                                        rx.text("📁"),
                                        rx.text(game.container_name, weight="bold"),
                                        rx.text(f"포트: {game.port}"),
                                        align="center",
                                        on_click=lambda: Games.move_to_url(game.port),
                                    ),
                                    rx.text(game.image),
                                    rx.hstack(
                                        rx.cond(
                                            game.status == GameStatus.RUNNING,
                                            rx.button(
                                                "중지",
                                                color_scheme="red",
                                                on_click=lambda: Games.stop_game(
                                                    game.id
                                                ),
                                            ),
                                            rx.button(
                                                "실행",
                                                on_click=lambda: Games.run_game(
                                                    game.id
                                                ),
                                            ),
                                        ),
                                        rx.button(
                                            "삭제",
                                            on_click=lambda: Games.delete_game(game.id),
                                        ),
                                        spacing="1",
                                    ),
                                    padding="10px",
                                    border="1px solid gray",
                                    border_radius="md",
                                    margin_bottom="5px",
                                    width="100%",
                                ),
                            ),
                            width="100%",
                            spacing="2",
                        ),
                        margin_bottom="2rem",
                        width="100%",
                    ),  # 디렉토리 목록
                    width="50%",
                ),
                rx.vstack(
                    rx.cond(
                        DirectoryState.directories != [],
                        rx.box(
                            rx.heading("📁 디렉토리", size="5", margin_bottom="1rem"),
                            # 현재 경로 표시
                            rx.box(
                                rx.hstack(
                                    rx.text("📍 현재 경로: ", weight="bold"),
                                    rx.text(DirectoryState.current_path),
                                    align="center",
                                ),
                                padding="15px",
                                background_color="gray.100",
                                border_radius="md",
                                margin_bottom="1rem",
                                width="100%",
                            ),
                            rx.vstack(
                                rx.foreach(
                                    DirectoryState.directories,
                                    lambda dir_name: rx.box(
                                        rx.hstack(
                                            rx.text("📁"),
                                            rx.text(dir_name, weight="bold"),
                                            align="center",
                                        ),
                                        padding="10px",
                                        border="1px solid gray",
                                        border_radius="md",
                                        margin_bottom="5px",
                                        width="100%",
                                        cursor="pointer",
                                        _hover={"background_color": "blue.50"},
                                        on_click=DirectoryState.set_selected_directory(
                                            dir_name
                                        ),
                                    ),
                                ),
                                width="100%",
                                spacing="2",
                            ),
                            margin_bottom="2rem",
                            width="100%",
                        ),
                    ),
                    # 파일 목록
                    rx.cond(
                        DirectoryState.files != [],
                        rx.box(
                            rx.heading("📄 파일", size="5", margin_bottom="1rem"),
                            rx.vstack(
                                rx.foreach(
                                    DirectoryState.files,
                                    lambda file_name: rx.box(
                                        rx.hstack(
                                            rx.text("📄"),
                                            rx.text(file_name),
                                            align="center",
                                        ),
                                        padding="10px",
                                        border="1px solid lightgray",
                                        border_radius="md",
                                        margin_bottom="5px",
                                        width="100%",
                                    ),
                                ),
                                width="100%",
                                spacing="2",
                            ),
                            width="100%",
                        ),
                    ),
                    width="50%",
                ),
                width="100%",
            ),
            width="100%",
            max_width="800px",
            spacing="4",
            on_mount=Games.on_load,
        ),
        padding="20px",
        on_mount=DirectoryState.refresh,
    )
