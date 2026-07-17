from services.technical_service import get_technical_indicators

def main():
    technical = get_technical_indicators("2330")
    print(technical)


if __name__ == "__main__":
    main()
