import json

def preprocess_sensor_data(raw_data: str) -> str:
    """
    Preprocesses raw sensor data to reduce token count by grouping by entity_id.

    Args:
        raw_data: A string containing the raw sensor data, with each line
                  representing a reading (tab-separated: entity_id, state, last_changed).
                  The first line is assumed to be the header.

    Returns:
        A JSON string representing the preprocessed data.
    """
    lines = raw_data.strip().split('\n')
    if not lines or len(lines) < 2:
        return json.dumps({}) # Return empty JSON if no data or only header

    # Skip header
    data_lines = lines[1:]

    processed_data = {}
    entity_id_to_short_code = {}
    next_short_code_id = 1

    for line in data_lines:
        parts = line.strip().split('\t')
        if len(parts) != 3:
            # Skip malformed lines
            continue
        
        entity_id, state, last_changed = parts

        if entity_id not in entity_id_to_short_code:
            short_code = f"s{next_short_code_id}"
            entity_id_to_short_code[entity_id] = short_code
            next_short_code_id += 1
            processed_data[short_code] = {
                "full_id": entity_id,
                "readings": []
            }
        
        short_code = entity_id_to_short_code[entity_id]
        processed_data[short_code]["readings"].append([last_changed, state])

    return json.dumps(processed_data, indent=2)

if __name__ == '__main__':
    # Example usage with the provided sample data
    sample_data = """entity_id	state	last_changed
sensor.octopus_energy_electricity_21j0023364_1200037135231_current_demand	228	2025-07-08T23:00:00.000Z
sensor.octopus_energy_electricity_21j0023364_1200037135231_current_demand	227	2025-07-08T23:01:01.902Z
sensor.octopus_energy_electricity_21j0023364_1200037135231_current_demand	219	2025-07-08T23:02:01.920Z
sensor.another_sensor_id_foo_bar_baz	10	2025-07-08T23:00:05.000Z
sensor.another_sensor_id_foo_bar_baz	12	2025-07-08T23:01:06.000Z
"""
    
    print("Original data (first few lines for brevity):")
    print('\n'.join(sample_data.strip().split('\n')[:6]))
    print("\n" + "="*30 + "\n")
    
    processed_json = preprocess_sensor_data(sample_data)
    
    print("Processed JSON data:")
    print(processed_json)

    # Example of how to load it back and verify
    # loaded_data = json.loads(processed_json)
    # print("\n" + "="*30 + "\n")
    # print("Loaded data (s1 full_id):", loaded_data.get("s1", {}).get("full_id"))
    # print("Loaded data (s1 first reading):", loaded_data.get("s1", {}).get("readings", [None])[0])
    # print("Loaded data (s2 full_id):", loaded_data.get("s2", {}).get("full_id"))
    # print("Loaded data (s2 first reading):", loaded_data.get("s2", {}).get("readings", [None])[0])

    # Test with the full sample data provided by the user
    print("\n" + "="*30 + "\n")
    print("Testing with full provided sample data (from sample_sensor_data.txt):")
    try:
        with open("sample_sensor_data.txt", "r") as f:
            full_sample_data = f.read()
        
        processed_full_json = preprocess_sensor_data(full_sample_data)
        print("\nProcessed JSON data (full sample):")
        print(processed_full_json)

        # Character count comparison for token reduction estimation
        original_char_count = len(full_sample_data)
        processed_char_count = len(processed_full_json)
        print(f"\nOriginal character count: {original_char_count}")
        print(f"Processed character count: {processed_char_count}")
        reduction_percentage = ((original_char_count - processed_char_count) / original_char_count) * 100
        print(f"Estimated reduction: {reduction_percentage:.2f}%")

    except FileNotFoundError:
        print("Error: sample_sensor_data.txt not found. Make sure it's in the same directory.")
    except Exception as e:
        print(f"An error occurred during full sample data processing: {e}")
