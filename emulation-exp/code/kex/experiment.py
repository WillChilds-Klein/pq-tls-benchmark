import csv
from multiprocessing import Pool
import os
import subprocess

# Our experiment used POOL_SIZE = 40
POOL_SIZE = 4

MEASUREMENTS_PER_TIMER = 100
TIMERS = 50

def run_subprocess(command, working_dir='.', expected_returncode=0):
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=working_dir
    )
    if(result.stderr):
        print(result.stderr)
    assert result.returncode == expected_returncode
    return result.stdout.decode('utf-8')

def change_qdisc(ns, dev, pkt_loss, delay):
    if pkt_loss == 0:
        command = [
            'sudo', 'ip', 'netns', 'exec', ns,
            'tc', 'qdisc', 'change',
            'dev', dev, 'root', 'netem',
            'limit', '1000',
            'delay', delay,
            'rate', '1000mbit'
        ]
    else:
        command = [
            'sudo', 'ip', 'netns', 'exec', ns,
            'tc', 'qdisc', 'change',
            'dev', dev, 'root', 'netem',
            'limit', '1000',
            'loss', '{0}%'.format(pkt_loss),
            'delay', delay,
            'rate', '1000mbit'
        ]

    print(" > " + " ".join(command))
    run_subprocess(command)

def time_handshake(security_policy, measurements):
    command = [
        'sudo', 'ip', 'netns', 'exec', 'cli_ns',
        './s_timer.o', security_policy, str(measurements)
    ]
    result = run_subprocess(command)
    return [float(i) for i in result.strip().split(',')]

def run_timers(security_policy, timer_pool):
    results_nested = timer_pool.starmap(time_handshake, [(security_policy, MEASUREMENTS_PER_TIMER)] * TIMERS)
    return [item for sublist in results_nested for item in sublist]

def get_rtt_ms():
    command = [
        'sudo', 'ip', 'netns', 'exec', 'cli_ns',
        'ping', '10.0.0.1', '-c', '30'
    ]

    print(" > " + " ".join(command))
    result = run_subprocess(command)

    result_fmt = result.splitlines()[-1].split("/")
    return result_fmt[4].replace(".", "p")

# Main
timer_pool = Pool(processes=POOL_SIZE)

if not os.path.exists('data'):
    os.makedirs('data')

security_policies = [
    'PQ-TLS-1-3-KYBER512',
    'PQ-TLS-1-3-KYBER768',
    'PQ-TLS-1-3-KYBER1024',
]

latencies = [
    '0.08ms',   # localhost
    '0.69ms',   # PDX => PDX
    '21ms',     # PDX => SFO
    '133ms',    # PDX => LHR
    '230ms',    # PDX => BOM
]
loss_rates = [0, 0.1, 0.5, 1, 1.5, 2, 2.5, 3]

for latency in latencies:
    # get emulated RTT
    change_qdisc('cli_ns', 'cli_ve', 0, delay=latency)
    change_qdisc('srv_ns', 'srv_ve', 0, delay=latency)
    rtt_str = get_rtt_ms()
    for security_policy in security_policies:
        with open('data/{}_{}ms.csv'.format(security_policy, rtt_str),'w') as out:
            # each line contains: pkt_loss, observations
            csv_out=csv.writer(out)
            for pkt_loss in loss_rates:
                change_qdisc('cli_ns', 'cli_ve', pkt_loss, delay=latency)
                change_qdisc('srv_ns', 'srv_ve', pkt_loss, delay=latency)
                result = run_timers(security_policy, timer_pool)
                result.insert(0, pkt_loss)
                csv_out.writerow(result)

timer_pool.close()
timer_pool.join()
