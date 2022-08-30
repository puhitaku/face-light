import gc
import json
import machine
import network
import neopixel
import time
import uasyncio

from collections import OrderedDict

from nanoweb import Nanoweb

wifi = network.WLAN(network.STA_IF)
n = 22 * 2
np = neopixel.NeoPixel(machine.Pin(12), n)

temperature = 4000
brightness = 255


class Coefficients:
    r = 1.0
    g = 1.0
    b = 1.0


coeff = Coefficients()

# Table from https://andi-siess.de/rgb-to-color-temperature/
kelvin2rgb_items = [
    (2000, (255, 138, 18)),
    (2100, (255, 142, 33)),
    (2200, (255, 147, 44)),
    (2300, (255, 152, 54)),
    (2400, (255, 157, 63)),
    (2500, (255, 161, 72)),
    (2600, (255, 165, 79)),
    (2700, (255, 169, 87)),
    (2800, (255, 173, 94)),
    (2900, (255, 177, 101)),
    (3000, (255, 180, 107)),
    (3100, (255, 184, 114)),
    (3200, (255, 187, 120)),
    (3300, (255, 190, 126)),
    (3400, (255, 193, 132)),
    (3500, (255, 196, 137)),
    (3600, (255, 199, 143)),
    (3700, (255, 201, 148)),
    (3800, (255, 204, 153)),
    (3900, (255, 206, 159)),
    (4000, (255, 209, 163)),
    (4100, (255, 211, 168)),
    (4200, (255, 213, 173)),
    (4300, (255, 215, 177)),
    (4400, (255, 217, 182)),
    (4500, (255, 219, 186)),
    (4600, (255, 221, 190)),
    (4700, (255, 223, 194)),
    (4800, (255, 225, 198)),
    (4900, (255, 227, 202)),
    (5000, (255, 228, 206)),
    (5100, (255, 230, 210)),
    (5200, (255, 232, 213)),
    (5300, (255, 233, 217)),
    (5400, (255, 235, 220)),
    (5500, (255, 236, 224)),
    (5600, (255, 238, 227)),
    (5700, (255, 239, 230)),
    (5800, (255, 240, 233)),
    (5900, (255, 242, 236)),
    (6000, (255, 243, 239)),
    (6100, (255, 244, 242)),
    (6200, (255, 245, 245)),
    (6300, (255, 246, 247)),
    (6400, (255, 248, 251)),
    (6500, (255, 249, 253)),
    (6600, (254, 249, 255)),
    (6700, (252, 247, 255)),
    (6800, (249, 246, 255)),
    (6900, (247, 245, 255)),
    (7000, (245, 243, 255)),
    (7100, (243, 242, 255)),
    (7200, (240, 241, 255)),
    (7300, (239, 240, 255)),
    (7400, (237, 239, 255)),
    (7500, (235, 238, 255)),
    (7600, (233, 237, 255)),
    (7700, (231, 236, 255)),
    (7800, (230, 235, 255)),
    (7900, (228, 234, 255)),
    (8000, (227, 233, 255)),
    (8100, (225, 232, 255)),
    (8200, (224, 231, 255)),
    (8300, (222, 230, 255)),
    (8400, (221, 230, 255)),
    (8500, (220, 229, 255)),
    (8600, (218, 229, 255)),
    (8700, (217, 227, 255)),
    (8800, (216, 227, 255)),
    (8900, (215, 226, 255)),
    (9000, (214, 225, 255)),
    (9100, (212, 225, 255)),
    (9200, (211, 224, 255)),
    (9300, (210, 223, 255)),
    (9400, (209, 223, 255)),
    (9500, (208, 222, 255)),
    (9600, (207, 221, 255)),
    (9700, (207, 221, 255)),
    (9800, (206, 220, 255)),
    (9900, (205, 220, 255)),
    (10000, (207, 218, 255)),
]

kelvin2rgb = OrderedDict(kelvin2rgb_items)
app = Nanoweb(port=80)


def log(fmt, *o):
    print('[{:08.3f}]'.format(time.ticks_ms() / 1000), fmt.format(*o))


def get_state():
    return {'free': gc.mem_free()}


def apply():
    global temperature, brightness, coeff

    t = kelvin2rgb[temperature]
    r = brightness / 255
    np.fill((int(t[0] * r * coeff.r), int(t[1] * r * coeff.g), int(t[2] * r * coeff.b)))
    np.write()


class Response:
    error = None

    def __init__(self, **kwargs):
        self.error = None
        for k, v in kwargs.items():
            setattr(self, k, v)

    def jsonify(self) -> str:
        d = dict()
        items = ((k, v) for k, v in self.__dict__.items() if not k.startswith('__'))
        for k, v in items:
            d[k] = v
        return json.dumps(d)


def respond(methods=('GET',)):
    """A mixin decorator to simplify handlers like Flask"""

    def decorator(fn):
        async def write_response(req, res):
            if isinstance(res, tuple):
                # Tuple = a tuple of status code and the body
                status, body = res
            else:
                # Others = implies "200 OK"
                status, body = 200, res

                # Start writing the response header
            await req.write('HTTP/1.1 {}\r\n'.format(status))

            if isinstance(body, dict) or isinstance(body, list):
                # Dict or list = jsonified
                await req.write('Content-Type: application/json\r\n\r\n')
                await req.write(json.dumps(body))
            elif isinstance(body, Response):
                await req.write('Content-Type: application/json\r\n\r\n')
                await req.write(body.jsonify())
            else:
                # Others = implies a plain text and be transmitted as-is
                await req.write('Content-Type: text/plain\r\n\r\n')
                await req.write(body)

        async def wrapper(req):
            log('{} {}', req.method, req.url)
            if req.method not in methods:
                await req.read(-1)
                await write_response(req, (405, Response(error='method not allowed')))
                return

            if req.method in ('PUT', 'POST', 'PATCH'):
                typ = req.headers.get('Content-Type', '')
                if typ != 'application/json':
                    log('bad request, invalid content type')
                    await req.read(-1)
                    await write_response(req, (400, Response(error='bad request, invalid content type')))
                    return

                content_len = req.headers.get('Content-Length')
                if content_len is None:
                    log('bad request, content length is not specified or zero')
                    await req.read(-1)
                    await write_response(req, (400, Response(error='bad request, content length is not specified or zero')))
                    return

                body = await req.read(int(content_len))
                req.body = body
                req.json = json.loads(body)

            await write_response(req, await fn(req))

        return wrapper

    return decorator


@app.route('/healthz')
@respond()
async def healthz(req):
    return 200, Response(message="I'm as ready as I'll ever be!", state=get_state())


@app.route('/coefficients')
@respond(methods=('GET', 'PUT'))
async def coefficients(req):
    global coeff

    if req.method == 'GET':
        return 200, Response(r=coeff.r, g=coeff.g, b=coeff.b)

    r = req.json.get('r')
    g = req.json.get('g')
    b = req.json.get('b')

    if r is None:
        return 400, Response(error='bad request, request object has no r key')
    elif g is None:
        return 400, Response(error='bad request, request object has no g key')
    elif b is None:
        return 400, Response(error='bad request, request object has no b key')

    if r > 1.0 or r < 0:
        return 400, Response(error='bad request, invalid r')
    elif g > 1.0 or g < 0:
        return 400, Response(error='bad request, invalid g')
    elif b > 1.0 or b < 0:
        return 400, Response(error='bad request, invalid b')

    log("r: {}, g: {}, b: {}", r, g, b)

    coeff.r, coeff.g, coeff.b = r, g, b
    apply()

    return 200, Response(r=r, g=g, b=b)


@app.route('/light')
@respond(methods=('GET', 'PUT'))
async def light(req):
    global temperature, brightness

    if req.method == 'GET':
        return 200, Response(temperature=temperature, brightness=brightness)

    t = req.json.get('temperature')
    if t is None:
        return 400, Response(error='bad request, request object has no temperature key')

    b = req.json.get('brightness')
    if b is None:
        return 400, Response(error='bad request, request object has no brightness key')

    if t < 2000 or t > 10000 or t % 100 != 0:
        return 400, Response(error='bad request, invalid temperature')

    if b < 0 or b > 255:
        return 400, Response(error='bad request, invalid brightness')

    temperature, brightness = t, b
    apply()

    return 200, Response(brightness=b, temperature=t)


def wifi_up(ssid, psk, hostname):
    if wifi.isconnected():
        return True

    log('Connecting to an AP')
    log('SSID: {}, PSK: (hidden)', ssid)

    wifi.active(True)
    wifi.config(dhcp_hostname=hostname)
    wifi.connect(ssid, psk)

    for _ in range(10):
        if wifi.isconnected():
            break
        time.sleep(1)
    else:
        log('Failed to connect: timed out')
        return False

    log('Successfully connected')
    return True


def main():
    with open('config.json', 'r') as f:
        conf = json.load(f)

    while True:
        ok = wifi_up(conf['ssid'], conf['psk'], conf['hostname'])
        if not ok:
            log('Failed to establish a Wi-Fi connection, resetting')
            machine.reset()

        log('Address: {}, Netmask: {}, GW: {}, DNS: {}', *wifi.ifconfig())
        gc.collect()

        loop = uasyncio.get_event_loop()
        loop.create_task(app.run())

        try:
            loop.run_forever()
        finally:
            log("Interrupting the server")


main()
