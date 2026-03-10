def applicant_data_to_dict(data: dict) -> dict:
    return_dict = {}

    for field in data.values():
        label = field["label"]
        value = field["value"]

        # Currently making assumption that preferred first/last always come after.
        # If that is not the case, will need to update this
        if label == "Preferred First Name":
            if value:
                label = "First Name"
            else:
                continue
        elif label == "Preferred Last Name":
            if value:
                label = "Last Name"
            else:
                continue
        elif label == "Preferred Pronouns":
            if value:
                label = "Pronouns"
            else:
                continue

        return_dict[label] = value

    return return_dict
