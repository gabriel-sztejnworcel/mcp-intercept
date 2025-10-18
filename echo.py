import sys

def main():
    try:
        while True:
            line = sys.stdin.readline()
            if not line:
                break
            print(line, end='')
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
