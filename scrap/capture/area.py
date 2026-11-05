import socket
import threading


class AreaCropControlMixin:
    def on_area_region_changed(self, region):
        self.area_region = dict(region)
        if self.area_crop_update_event is None:
            return
        with self.area_crop_lock:
            self.pending_area_region = dict(region)
        self.area_crop_update_event.set()

    def _start_area_crop_control(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as port_socket:
            port_socket.bind(("127.0.0.1", 0))
            self.area_crop_port = port_socket.getsockname()[1]

        self.area_crop_stop = threading.Event()
        self.area_crop_update_event = threading.Event()
        self.pending_area_region = dict(self.area_region)
        self.area_crop_error = None
        self.area_crop_thread = threading.Thread(
            target=self._area_crop_command_worker,
            args=(self.area_crop_port, self.area_crop_stop),
            daemon=True,
        )
        self.area_crop_thread.start()
        return self.area_crop_port

    def _area_crop_command_worker(self, port, stop_event):
        import zmq

        context = zmq.Context()
        client = None

        def connect_client():
            new_client = context.socket(zmq.REQ)
            new_client.setsockopt(zmq.LINGER, 0)
            new_client.setsockopt(zmq.SNDTIMEO, 200)
            new_client.connect(f"tcp://127.0.0.1:{port}")
            return new_client

        client = connect_client()
        last_region = None
        try:
            while not stop_event.is_set():
                if not self.area_crop_update_event.wait(0.1):
                    continue
                self.area_crop_update_event.clear()
                with self.area_crop_lock:
                    region = dict(self.pending_area_region)
                if region == last_region:
                    continue
                monitor_left = self.area_region_bounds["left"]
                monitor_top = self.area_region_bounds["top"]
                values = {
                    "w": region["width"],
                    "h": region["height"],
                    "x": region["left"] - monitor_left,
                    "y": region["top"] - monitor_top,
                }
                try:
                    for option, value in values.items():
                        client.send_string(f"crop@area {option} {value}")
                        if not client.poll(250):
                            raise zmq.Again()
                        response = client.recv_string()
                        if not response.startswith("0 "):
                            raise RuntimeError(response)
                    last_region = region
                except (zmq.ZMQError, RuntimeError) as exc:
                    self.area_crop_error = str(exc)
                    client.close(0)
                    client = connect_client()
                    with self.area_crop_lock:
                        self.pending_area_region = region
                    self.area_crop_update_event.set()
                    stop_event.wait(0.1)
        finally:
            client.close(0)
            context.term()

    def _stop_area_crop_control(self):
        if self.area_crop_stop is not None:
            self.area_crop_stop.set()
        if self.area_crop_update_event is not None:
            self.area_crop_update_event.set()
        if self.area_crop_thread is not None:
            self.area_crop_thread.join(timeout=2)
        self.area_crop_port = None
        self.area_crop_stop = None
        self.area_crop_thread = None
        self.area_crop_update_event = None
