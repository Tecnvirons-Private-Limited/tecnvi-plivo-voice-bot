import phonenumbers
from phonenumbers import PhoneNumberType, NumberParseException

# Function to extract mobile numbers from a raw string 
# Change the country code to your desired country
# For example, for Nepal, use "NP"
# For India, use "IN"
def extract_mobile_numbers(raw, country = "NP"):
    valid_mobiles = []
    for i in range(len(raw)):
        for j in range(i+8, min(i+16, len(raw)+1)):
            try:
                number = phonenumbers.parse(raw[i:j], "NP")
                if (
                    phonenumbers.is_valid_number(number) and
                    phonenumbers.region_code_for_number(number) == country and
                    phonenumbers.number_type(number) == PhoneNumberType.MOBILE
                ):
                    # Format as E.164 (e.g., +9779869730965)
                    formatted = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
                    valid_mobiles.append(formatted)
            except NumberParseException:
                continue
    return list(set(valid_mobiles))  # Ensure uniqueness

# Run it
