import argparse
from pathlib import Path


def copy_folder_contents(folder_name, output_file):
    root_path = Path(folder_name)
    output_path = Path(output_file).resolve()

    if not root_path.is_dir():
        print(f"Error: The folder '{folder_name}' does not exist.")
        return

    with open(output_path, 'w', encoding='utf-8') as out_f:
        # rglob('*') recursively finds all files in the folder and subfolders
        for file_path in root_path.rglob('*'):

            # Skip directories and the output file itself to prevent infinite loops
            if not file_path.is_file() or file_path.resolve() == output_path:
                continue

            # Calculate the path including the root folder name (e.g., 'server/api/main.py')
            rel_path = file_path.relative_to(root_path.parent)

            try:
                # Read the file content
                with open(file_path, 'r', encoding='utf-8') as in_f:
                    content = in_f.read()

                # Write to the consolidated file in the requested format
                out_f.write(f"#{rel_path}\n")
                out_f.write(content)
                out_f.write("\n\n")

            except UnicodeDecodeError:
                # Silently skip binary files (like .png, .pyc, etc.)
                print(f"Skipped binary or non-UTF-8 file: {rel_path}")

    print(f"Done! All text files from '{folder_name}' have been saved to '{output_file}'.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Consolidate folder files into a single text file.")
    parser.add_argument("folder", help="The name or path of the folder to read")
    parser.add_argument("-o", "--output", default="combined_output.txt",
                        help="The name of the output text file (default: combined_output.txt)")

    args = parser.parse_args()
    copy_folder_contents(args.folder, args.output)
